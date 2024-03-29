# ec2-imagebuilder-vmdk-export

[EC2 Image Builder](https://aws.amazon.com/image-builder/) simplifies the building, testing, and deployment of Virtual Machine and container images for use on AWS or on-premises. Customers looking to create custom AMIs ([Amazon Machine Image](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/AMIs.html)) or container images can leverage EC2 Image Builder to significantly reduce the effort of keeping images up-to-date and secure through its simple graphical interface, built-in automation, and AWS-provided security settings. 

There are times, when customers may wish to have access to their custom AMIs in their on-premises environments. AWS provides the [VM Import/Export](https://docs.aws.amazon.com/vm-import/latest/userguide/what-is-vmimport.html) service which enables customers to import virtual machine (VM) images from their existing virtualization environment to Amazon EC2, and then export them back. The service enables the migration of applications and workloads to Amazon EC2, copying of a customer's VM image catalog to Amazon EC2, or the creation of a repository of VM images for backup and disaster recovery.

An additional note, with respect to EC2 Image Builder, is that the service includes [distribution settings](https://docs.aws.amazon.com/imagebuilder/latest/userguide/manage-distribution-settings.html) that allow for the *publishing* and *sharing* of AMIs. *Publishing* an AMI allows customers to define the AWS accounts and regions to which the generated AMI will be copied. *Sharing* an AMI allows customers to define the AWS accounts and regions to which the generated AMI will be shared. AWS accounts that have been nominated as targets for AMI sharing are able to launch EC2 instances based on those AMIs.

The AWS CLI fully supports [creating and updating distribution settings for AMIs](https://docs.aws.amazon.com/imagebuilder/latest/userguide/crud-ami-distribution-settings.html).

AWS CloudFormation offers the capability of defining [distribution settings for EC2 Image Builder](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-imagebuilder-distributionconfiguration-distribution.html). However, at the time of writing this blog post, AWS CloudFormation does not provide the capability of defining the target accounts to which a generated AMI will be published. Specifically, the `targetAccountIds` attribute is not currently exposed through AWS CloudFormation.

This project provides a CDK stack that creates an EC2 Image Builder pipeline to create, distribute and share a custom AMI. The project contains a CDK [Custom Resource](https://docs.aws.amazon.com/cdk/api/latest/docs/custom-resources-readme.html) that allows customers to access the full set of distribution settings for EC2 Image Builder, including the `targetAccountIds` attribute.

The project can be executed using a single AWS account.

If, however, a customer wishes to distribute and share an AMI to other AWS accounts then 3 accounts would be required.

1. A *tooling* account where the CDK stack is deployed and the project resources are created.
2. A *publishing* account (or accounts) to which the generated AMI would be published.
3. A *sharing* account (or accounts) to whom the generated AMI would be shared.

The code will only deploy resources into the *tooling* account. The existence of the *publishing* and *sharing* accounts are only required in order to set the respective EC2 Image Builder distribution configuration settings.

----

* [Solution architecture](#solution-architecture)
* [Deploying the project](#deploying-the-project)
* [Executing the project](#executing-the-project)
* [Clean up the project](#clean-up-the-project)
* [Executing unit tests](#executing-unit-tests)
* [Executing static code analysis tool](#executing-static-code-analysis-tool)
* [Security](#security)
* [License](#license)

# Solution architecture

The solution architecture discussed in this post is presented below:

![Solution architecture](docs/assets/solution_architecture.png)

1. The EC2 Image Builder pipeline is *run* to create, distribute and share the AMI.
2. A message is published to a SNS topic containing the *ARN* of the executing EC2 Image Builder pipeline.
3. A Lambda function, associated with the SNS topic, invokes an AWS Step Functions State Machine.
4. The AWS Step Functions State Machine, using a combination of Lambda functions and State Machine wait states, polls the AWS EC2 API to determine when 
the AMI has entered the `Available` state.
5. Once the AMI has entered the `Available` state, the State Machine proceeds to begin the AMI export process.
6. The State Machine polls the AWS EC2 API to determine when 
the VM export process has entered the `Completed` state.
7. Once the VM export process has entered the `Completed` state, the State Machine proceeds to invoke a Lambda function which creates a pre-signed S3 URL linked to the exported `.vmdk` file that has been saved to a S3 bucket during the export process.
8. The Lambda function generates an email message which it publishes to a SNS topic.
9. The SNS topic includes an email subscription, which is sent the email message containing the instructions on how to download the exported `.vmdk` file.

# Deploying the project

The project code uses the Python flavour of the AWS CDK ([Cloud Development Kit](https://aws.amazon.com/cdk/)). In order to execute the code, please ensure that you have fulfilled the [AWS CDK Prerequisites for Python](https://docs.aws.amazon.com/cdk/latest/guide/work-with-cdk-python.html).

Additionally, the project assumes:

* configuration of [AWS CLI Environment Variables](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-envvars.html).
* the availability of a `bash` (or compatible) shell environment.
* a [Docker](https://docs.docker.com/get-docker/) installation.

The project requires that the AWS account is [bootstrapped](https://docs.aws.amazon.com/de_de/cdk/latest/guide/bootstrapping.html) in order to allow the deployment of the CDK stack.

```
# navigate to project directory
cd ec2-imagebuilder-vmdk-export

# install and activate a Python Virtual Environment
python3 -m venv .venv
source .venv/bin/activate

# install dependant libraries
python -m pip install -r requirements.txt

# bootstrap the account to permit CDK deployments
cdk bootstrap
```

Upon successful completion of `cdk bootstrap`, the project is ready to be deployed.

Before deploying the project, some configuration parameters need to be be defined in the [cdk.json](cdk.json) file.

```
{
  "app": "python3 app.py",
  "context": {
    "@aws-cdk/aws-apigateway:usagePlanKeyOrderInsensitiveId": true,
    "@aws-cdk/core:enableStackNameDuplicates": "true",
    "aws-cdk:enableDiffNoFail": "true",
    "@aws-cdk/core:stackRelativeExports": "true",
    "@aws-cdk/aws-ecr-assets:dockerIgnoreSupport": true,
    "@aws-cdk/aws-secretsmanager:parseOwnedSecretName": true,
    "@aws-cdk/aws-kms:defaultKeyPolicies": true,
    "@aws-cdk/aws-s3:grantWriteWithoutAcl": true,
    "@aws-cdk/aws-ecs-patterns:removeDefaultDesiredCount": true,
    "@aws-cdk/aws-rds:lowercaseDbIdentifier": true,
    "@aws-cdk/aws-efs:defaultEncryptionAtRest": true,
    "@aws-cdk/aws-lambda:recognizeVersionProps": true,
    "@aws-cdk/aws-cloudfront:defaultSecurityPolicyTLSv1.2_2021": true
  },
  "projectSettings": {
    "vpc": {
      "vpc_id": "<<ADD_VPD_ID_HERE>>",
      "subnet_id": "<<ADD_SUBNET_ID_HERE>>"
    },
    "imagebuilder": {
      "baseImageArn": "amazon-linux-2-x86/2021.4.29",
      "ebsVolumeSize": 8,
      "instanceTypes": [
        "t2.medium"
      ],
      "version": "1.0.0",
      "imageBuilderEmailAddress": "email@domian.com",
      "extraTags": {
        "imagePipeline": "AMIBuilder"
      },
      "distributionList": [
        "account1",
        "account2"
      ],
      "amiPublishingRegions": [
        "<<ADD_AMI_PUBLISHING_REGION_HERE>>"
      ],
      "amiPublishingTargetIds": [
        "<<ADD_AMI_PUBLISHING_TARGET_ACCOUNT_IDS_HERE>>"
      ],
      "amiSharingIds": [
        "<<ADD_AMI_SHARING_ACCOUNT_IDS_HERE>>"
      ]
    }
  }
}
```

Add your environment specific values to the [cdk.json](cdk.json) file as follows:

* Replace placeholder `<<ADD_VPD_ID_HERE>>` with your Vpc Id.
* Replace placeholder `<<ADD_SUBNET_ID_HERE>>` with your Subnet Id. The subnet you select must be part of the Vpc you defined in the previous step.
* Replace placeholder `<<ADD_AMI_PUBLISHING_REGION_HERE>>` with the AWS regions to which you would like to publish the generated AMIs.
* Replace placeholder `<<ADD_AMI_PUBLISHING_TARGET_ACCOUNT_IDS_HERE>>` with the AWS account ids to whom you would like to publish the generated AMIs.
* Replace placeholder `<<ADD_AMI_SHARING_ACCOUNT_IDS_HERE>>` with the AWS account ids to whom you would like to share the generated AMIs.

**NOTE:** Customers wishing to execute the project within a *single* AWS account can add their current AWS account and AWS region details to: 

* `<<ADD_AMI_PUBLISHING_REGION_HERE>>`
* `<<ADD_AMI_PUBLISHING_TARGET_ACCOUNT_IDS_HERE>>`
* `<<ADD_AMI_SHARING_ACCOUNT_IDS_HERE>>`

This will prevent the need for using additional AWS accounts for AMI distribution and sharing.

With the placeholders replaced in the [cdk.json](cdk.json) file, the CDK stack can be deployed with the command below.

```
cdk deploy
```

Following a successful deployment, verify that two new stacks have been created within the *tooling* AWS account:

* `CDKToolkit`
* `EC2ImageBuilderVmdkExport-main`

Log into the AWS Console → navigate to the CloudFormation console:

![CDK CloudFormation deployment](docs/assets/screenshots/01-cloudformation-deployed.png)

Verify the distribution settings of EC2 Image Builder.

1. Log into the AWS Console → navigate to the EC2 Image Builder console.
2. Click on the pipeline with name `ami-share-pipeline-main` to open the detailed pipeline view.
3. Click on the *Distribution settings* and review the *Distribution details*.
4. Confirm that the following values match the parameter values defined in the [cdk.json](cdk.json) file.
    1. Region
    2. Target accounts for distribution
    3. Accounts with shared permissions

![EC2 Image Builder AMI distribution settings](docs/assets/screenshots/02-distribution-settings.png)

The CDK stack has successfully deployed the EC2 Image Builder and the *Target accounts for distribution* value has been correctly set through the use of a CustomResource Lambda function.

Please note that in order to distribute the generated AMI to other AWS accounts it is necessary to [set up cross-account AMI distribution with Image Builder](https://docs.aws.amazon.com/imagebuilder/latest/userguide/cross-account-dist.html).

Verify the Step Function diagram in AWS State Machine.

1. Log into the AWS Console → navigate to the Step Functions console.
2. Click on the State Machine name `VMDKExportStateMachinemainXXXXX-XXXXX` to open the detailed state machine view.
3. Click on the *Definition* tab and verify that the State Machine diagram matches the diagram below:

![Step Functions State Machine](docs/assets/screenshots/03-state-machine-graph.png)

# Executing the project

The project includes an [execute-pipeline](execute-pipeline.sh) script that can be used to trigger the AMI creation, distribution and sharing via the EC2 Image Builder. Once the EC2 Image Builder image pipeline has been triggered, the script then publishes a message to a SNS topic containing the ARN of the executed EC2 Image Builder image pipeline. Once triggered, these processes are executed using an event driven design terminating in the AMI being exported to an S3 bucket in the `.vmdk` format and an email being sent to the email account that is subscribed to the SNS topic.

A sample invocation is shown below:

```bash
bash execute-pipeline.sh
```

![Execute pipeline](docs/assets/screenshots/04-execute-pipeline.png)

Once triggered, the process can take up to 2 hours to complete:

* creation, distribution and sharing of the AMI can take up to 1 hour
* exporting of the AMI to `.vmdk` format can take up to 1 hour

Monitor the progress of AMI creation, distribution and sharing.

1. Log into the AWS Console → navigate to the EC2 Image Builder console.
2. Click on the pipeline with name `ami-share-pipeline-main` to open the detailed pipeline view.
3. Click on the *Output images* and review the *Output images* table.
4. The creation, distribution and sharing of the AMI is completed once the *Status* is `Available`.

![AMI Available state](docs/assets/screenshots/05-ami-available.png)

Monitor the progress of the VMDK export process.

1. Log into the AWS Console → navigate to the Step Functions console.
2. Click on the State Machine name `VMDKExportStateMachinemainXXXXX-XXXXX` to open the detailed state machine view.
3. Click on the *Executions* tab and click on the execution with the `Running` state.
4. You will be able to visualize the progress through the State Machine steps.

![State Machine execution](docs/assets/screenshots/06-state-machine-execution.png)

Upon completion of the VMDK export process, an email similar to that shown below will be sent to the email address nominated in the `imageBuilderEmailAddress` field of the [cdk.json](cdk.json) file.

![Completion email](docs/assets/screenshots/07-vmdk-export-email.png)

# Clean up the project

Project clean-up is a 2 step process:

1. Destroy the CDK stack.
2. Delete the *CDKToolkit* stack from CloudFormation.

Delete the stack deployed by CDK with the command below:

```
cdk destroy
```

Delete the CDKToolkit CloudFormation stack.

1. Log into the AWS Console → navigate to the *CloudFormation* console.
2. Navigate to *Stacks*.
3. Select the **CDKToolkit**.
4. Click the *Delete* button.

# Executing unit tests

Unit tests for the project can be executed via the command below:

```bash
python3 -m venv .venv
source .venv/bin/activate
cdk synth && python -m pytest -v -c ./tests/pytest.ini
```

# Executing static code analysis tool

The solution includes [Checkov](https://github.com/bridgecrewio/checkov) which is a static code analysis tool for infrastructure as code (IaC).

The static code analysis tool for the project can be executed via the commands below:

```bash
python3 -m venv .venv
source .venv/bin/activate
rm -fr cdk.out && cdk synth && checkov --config-file checkov.yaml
```

**NOTE:** The Checkov tool has been configured to skip certain checks.

The Checkov configuration file, [checkov.yaml](checkov.yaml), contains a section named `skip-check`.

```
skip-check:
  - CKV_AWS_7     # Ensure rotation for customer created CMKs is enabled
  - CKV_AWS_18    # Ensure the S3 bucket has access logging enabled
  - CKV_AWS_19    # Ensure the S3 bucket has server-side-encryption enabled
  - CKV_AWS_20    # Ensure the S3 bucket does not allow READ permissions to everyone
  - CKV_AWS_21    # Ensure the S3 bucket has versioning enabled
  - CKV_AWS_23    # Ensure every security groups rule has a description
  - CKV_AWS_24    # Ensure no security groups allow ingress from 0.0.0.0:0 to port 22
  - CKV_AWS_25    # Ensure no security groups allow ingress from 0.0.0.0:0 to port 3389
  - CKV_AWS_26    # Ensure all data stored in the SNS topic is encrypted
  - CKV_AWS_33    # Ensure KMS key policy does not contain wildcard (*) principal
  - CKV_AWS_40    # Ensure IAM policies are attached only to groups or roles (Reducing access management complexity may in-turn reduce opportunity for a principal to inadvertently receive or retain excessive privileges.)
  - CKV_AWS_45    # Ensure no hard-coded secrets exist in lambda environment
  - CKV_AWS_53    # Ensure S3 bucket has block public ACLS enabled
  - CKV_AWS_54    # Ensure S3 bucket has block public policy enabled
  - CKV_AWS_55    # Ensure S3 bucket has ignore public ACLs enabled
  - CKV_AWS_56    # Ensure S3 bucket has 'restrict_public_bucket' enabled
  - CKV_AWS_57    # Ensure the S3 bucket does not allow WRITE permissions to everyone
  - CKV_AWS_60    # Ensure IAM role allows only specific services or principals to assume it
  - CKV_AWS_61    # Ensure IAM role allows only specific principals in account to assume it
  - CKV_AWS_107   # Ensure IAM policies does not allow credentials exposure
  - CKV_AWS_108   # Ensure IAM policies does not allow data exfiltration
  - CKV_AWS_109   # Ensure IAM policies does not allow permissions management without constraints
  - CKV_AWS_110   # Ensure IAM policies does not allow privilege escalation
  - CKV_AWS_111   # Ensure IAM policies does not allow write access without constraints
  - CKV_AWS_116   # Ensure that AWS Lambda function is configured for a Dead Letter Queue(DLQ)
  - CKV_AWS_173   # Check encryption settings for Lambda environmental variable
```

These checks represent best practices in AWS and should be enabled (or at the very least the security risk of not enabling the checks should be accepted and understood) for production systems. 

In the context of this solution, these specific checks have not been remediated in order to focus on the core elements of the solution.

# Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

# License

This library is licensed under the MIT-0 License. See the LICENSE file.