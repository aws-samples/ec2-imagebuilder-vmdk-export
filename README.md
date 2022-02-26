# ec2-imagebuilder-vmdk-export

CDK stack that contains an event-driven approach to AMI creation, distribution and sharing as well as the exporting of the AMI to `vmdk` format. In addition, the project contains a CustomResource with Lambda function to allow the setting of the `targetAccountIds` attribute of the EC2 Image Builder AMI distribution settings which is not currently supported in CloudFormation or CDK.

---

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

In addition to the [AWS CDK Prerequisites for Python](https://docs.aws.amazon.com/cdk/latest/guide/work-with-cdk-python.html), the project also uses the [AWS Lambda Python](https://docs.aws.amazon.com/cdk/api/latest/docs/aws-lambda-python-readme.html) module. This module requires an installation of [Docker](https://docs.docker.com/get-docker/) in order to build the Python function with its declared dependencies.

The relevant section of the CDK [vmdk_export.py](stacks/vmdkexport/vmdk_export.py) stack, in which the Custom Resource and Lambda definition for configuring the AMI distribution and sharing settings, is shown below:

```
# Create ami distribution lambda function - this is required because 
# EC2 ImageBuilder AMI distribution setting targetAccountIds
# is not supported by CloudFormation (as of September 2021).
# see https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-imagebuilder-distributionconfiguration.html

# Create a role for the amidistribution lambda function
amidistribution_lambda_role = iam.Role(
    scope=self,
    id=f"amidistributionLambdaRole-{CdkUtils.stack_tag}",
    assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
    managed_policies=[
        iam.ManagedPolicy.from_aws_managed_policy_name(
            "service-role/AWSLambdaBasicExecutionRole"
        )
    ]
)
amidistribution_lambda_role.add_to_policy(
    iam.PolicyStatement(
        effect=iam.Effect.ALLOW,
        resources=[ami_share_distribution_config.attr_arn],
        actions=[
            "imagebuilder:UpdateDistributionConfiguration"
        ]
    )
)
amidistribution_lambda_role.add_to_policy(
    iam.PolicyStatement(
        effect=iam.Effect.ALLOW,
        resources=[f"arn:aws:ssm:{core.Aws.REGION}:{core.Aws.ACCOUNT_ID}:parameter/{CdkUtils.stack_tag}-AmiSharing/*"],
        actions=[
                "ssm:GetParameter",
                "ssm:GetParameters",
                "ssm:GetParametersByPath"
        ]
    )
)

# create the lambda that will use boto3 to set the 'targetAccountIds'
# ami distribution setting currently not supported in Cloudformation
ami_distribution_lambda = aws_lambda.Function(
    scope=self,
    id=f"amiDistributionLambda-{CdkUtils.stack_tag}",
    code=aws_lambda.Code.asset("stacks/amishare/resources/amidistribution"),
    handler="ami_distribution.lambda_handler",
    runtime=aws_lambda.Runtime.PYTHON_3_6,
    role=amidistribution_lambda_role
)

# Provider that invokes the ami distribution lambda function
ami_distribution_provider = custom_resources.Provider(
    self, 
    f'AmiDistributionCustomResourceProvider-{CdkUtils.stack_tag}',
    on_event_handler=ami_distribution_lambda
)

# Create a SSM Parameters for AMI Publishing and Sharing Ids
# so as not to hardcode the account id values in the Lambda
ssm_ami_publishing_target_ids = ssm.StringListParameter(
    self, f"AmiPublishingTargetIds-{CdkUtils.stack_tag}",
    parameter_name=f'/{CdkUtils.stack_tag}-AmiSharing/AmiPublishingTargetIds',
    string_list_value=config['imagebuilder']['amiPublishingTargetIds']
)

ssm_ami_sharing_ids = ssm.StringListParameter(
    self, f"AmiSharingAccountIds-{CdkUtils.stack_tag}",
    parameter_name=f'/{CdkUtils.stack_tag}-AmiSharing/AmiSharingAccountIds',
    string_list_value=config['imagebuilder']['amiSharingIds']
)

# The custom resource that uses the ami distribution provider to supply values
ami_distribution_custom_resource = core.CustomResource(
    self, 
    f'AmiDistributionCustomResource-{CdkUtils.stack_tag}',
    service_token=ami_distribution_provider.service_token,
    properties = {
        'CdkStackName': CdkUtils.stack_tag,
        'AwsDistributionRegions': config['imagebuilder']['amiPublishingRegions'],
        'ImageBuilderName': f'AmiDistributionConfig-{CdkUtils.stack_tag}',
        'AmiDistributionName': f"AmiShare-{CdkUtils.stack_tag}" + "-{{ imagebuilder:buildDate }}",
        'AmiDistributionArn': ami_share_distribution_config.attr_arn,
        'PublishingAccountIds': ssm_ami_publishing_target_ids.parameter_name,
        'SharingAccountIds': ssm_ami_sharing_ids.parameter_name
    }
)

ami_distribution_custom_resource.node.add_dependency(ami_share_distribution_config)

# The result obtained from the output of custom resource
ami_distriubtion_arn = core.CustomResource.get_att_string(ami_distribution_custom_resource, attribute_name='AmiDistributionArn')
```

The [ami_distribution.py](/stacks/vmdkexport/resources/amidistribution/ami_distribution.py) Lambda function, called by the Custom Resource, is shown below:

```
##################################################
## EC2 ImageBuilder AMI distribution setting targetAccountIds
## is not supported by CloudFormation (as of September 2021).
## https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-imagebuilder-distributionconfiguration.html
##
## This lambda function uses Boto3 for EC2 ImageBuilder in order 
## to set the AMI distribution settings which are currently missing from 
## CloudFormation - specifically the targetAccountIds attribute
## https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/imagebuilder.html
##################################################

import os
import boto3
import botocore
import json
import logging

def get_ssm_parameter(ssm_param_name: str, aws_ssm_region: str):
    ssm = boto3.client('ssm', region_name=aws_ssm_region)
    parameter = ssm.get_parameter(Name=ssm_param_name, WithDecryption=False)
    return parameter['Parameter']

def get_distributions_configurations(
        aws_distribution_regions, 
        ami_distribution_name,
        publishing_account_ids, 
        sharing_account_ids
    ):

    distribution_configs = []

    for aws_region in aws_distribution_regions:
        distribution_config = {
            'region': aws_region,
            'amiDistributionConfiguration': {
                'name': ami_distribution_name,
                'description': f'AMI Distribution configuration for {ami_distribution_name}',
                'targetAccountIds': publishing_account_ids,
                'amiTags': {
                    'PublishTargets': ",".join(publishing_account_ids),
                    'SharingTargets': ",".join(sharing_account_ids)
                },
                'launchPermission': {
                    'userIds': sharing_account_ids
                }
            }
        }

        distribution_configs.append(distribution_config)

    return distribution_configs

def lambda_handler(event, context):
    # set logging
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    
    # print the event details
    logger.debug(json.dumps(event, indent=2))

    props = event['ResourceProperties']
    cdk_stack_name = props['CdkStackName']
    aws_region = os.environ['AWS_REGION']
    aws_distribution_regions = props['AwsDistributionRegions']
    imagebuiler_name = props['ImageBuilderName']
    ami_distribution_name = props['AmiDistributionName']
    ami_distribution_arn = props['AmiDistributionArn']
    ssm_publishing_account_ids_param_name = props['PublishingAccountIds']
    ssm_sharing_account_ids_param_name = props['SharingAccountIds']

    publishing_account_ids = get_ssm_parameter(ssm_publishing_account_ids_param_name, aws_region)['Value'].split(",")
    sharing_account_ids = get_ssm_parameter(ssm_sharing_account_ids_param_name, aws_region)['Value'].split(",")

    logger.info(publishing_account_ids)
    logger.info(sharing_account_ids)

    if event['RequestType'] != 'Delete':
        try:
            client = boto3.client('imagebuilder')
            response = client.update_distribution_configuration(
                distributionConfigurationArn=ami_distribution_arn,
                description=f"AMI Distribution settings for: {imagebuiler_name}",
                distributions=get_distributions_configurations(
                    aws_distribution_regions=aws_distribution_regions,
                    ami_distribution_name=ami_distribution_name,
                    publishing_account_ids=publishing_account_ids,
                    sharing_account_ids=sharing_account_ids
                )
            )
        except botocore.exceptions.ClientError as err:
            raise err

    output = {
        'PhysicalResourceId': f"ami-distribution-id-{cdk_stack_name}",
        'Data': {
            'AmiDistributionArn': ami_distribution_arn
        }
    }
    logger.info("Output: " + json.dumps(output))
    return output
```

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

On Linux/MacOS:

```bash
./execute-pipeline.sh
```

On Windows:

```bash
execute-pipeline.bat
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

# Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

# License

This library is licensed under the MIT-0 License. See the LICENSE file.