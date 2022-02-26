from aws_cdk import (
    core,
    aws_imagebuilder as imagebuilder,
    aws_iam as iam,
    aws_sns as sns,
    aws_sns_subscriptions as sns_subscriptions,
    aws_ec2 as ec2,
    aws_ssm as ssm,
    aws_kms as kms,
    aws_s3 as s3,
    aws_lambda,
    aws_lambda_python,
    aws_stepfunctions as stepfunctions,
    aws_stepfunctions_tasks as stepfunctions_tasks,
    custom_resources
)

from utils.CdkUtils import CdkUtils


class VmdkExportStack(core.Stack):

    LAMBDA_TIMEOUT_DEFAULT = core.Duration.seconds(20)

    def __init__(self, scope: core.Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        config = CdkUtils.get_project_settings()

        # Retrieve VPC information via lookup
        ami_share_vpc = ec2.Vpc.from_lookup(self, "VPC",
            vpc_id = config['vpc']['vpc_id']
        )

        # create a KMS key to encrypt project contents
        kms_key = kms.Key(
            self, 
            f"ami-share-kms-key-{CdkUtils.stack_tag}",
            admins=[iam.AccountPrincipal(account_id=core.Aws.ACCOUNT_ID)],
            enable_key_rotation=True,
            enabled=True,
            description="KMS key used with EC2 Imagebuilder Ami Share project",
            removal_policy=core.RemovalPolicy.DESTROY,
            alias=f"ami-share-kms-key-alias-{CdkUtils.stack_tag}"
        )

        kms_key.grant_encrypt_decrypt(iam.ServicePrincipal(service=f'imagebuilder.{core.Aws.URL_SUFFIX}'))

        s3_bucket = s3.Bucket(
            self,
            f"vmdk-export-bucket-{CdkUtils.stack_tag}",
            bucket_name=f"vmdk-export-bucket-{CdkUtils.stack_tag}",
            removal_policy=core.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            versioned=False,
            public_read_access=False,
            block_public_access=s3.BlockPublicAccess(
                block_public_acls=True,
                block_public_policy=True,
                ignore_public_acls=True,
                restrict_public_buckets=True
            ),
            encryption=s3.BucketEncryption.S3_MANAGED
        )

        # below role is assumed by the ImageBuilder ec2 instance
        ami_share_image_role = iam.Role(self, f"ami-share-image-role-{CdkUtils.stack_tag}", assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"))
        ami_share_image_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore"))
        ami_share_image_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("EC2InstanceProfileForImageBuilder"))
        kms_key.grant_encrypt_decrypt(ami_share_image_role)
        kms_key.grant(ami_share_image_role, "kms:Describe*")
        ami_share_image_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "logs:CreateLogStream",
                "logs:CreateLogGroup",
                "logs:PutLogEvents"
            ],
            resources=[
                core.Arn.format(components=core.ArnComponents(
                    service="logs",
                    resource="log-group",
                    resource_name="aws/imagebuilder/*"
                ), stack=self)
            ],
        ))

        # create an instance profile to attach the role
        instance_profile = iam.CfnInstanceProfile(
            self, f"ami-share-imagebuilder-instance-profile-{CdkUtils.stack_tag}",
            instance_profile_name=f"ami-share-imagebuilder-instance-profile-{CdkUtils.stack_tag}",
            roles=[ami_share_image_role.role_name]
        )

        ssm.StringListParameter(
            self, f"ami-share-distribution-list-{CdkUtils.stack_tag}",
            parameter_name=f'/{CdkUtils.stack_tag}-AmiSharePipeline/DistributionList',
            string_list_value=config["imagebuilder"]['distributionList']
        )

        sns_topic = sns.Topic(
            self, f"ami-share-imagebuilder-topic-{CdkUtils.stack_tag}",
            topic_name=f"ami-share-imagebuilder-topic-{CdkUtils.stack_tag}",
            master_key=kms_key
        )

        sns.Subscription(
            self, f"ami-share-imagebuilder-subscription-{CdkUtils.stack_tag}",
            topic=sns_topic,
            endpoint=config["imagebuilder"]["imageBuilderEmailAddress"],
            protocol=sns.SubscriptionProtocol.EMAIL
        )

        sns_topic.grant_publish(ami_share_image_role)
        kms_key.grant_encrypt_decrypt(iam.ServicePrincipal(service=f'sns.{core.Aws.URL_SUFFIX}'))

        # SG for the image build
        ami_share_imagebuilder_sg = ec2.SecurityGroup(
            self, f"ami-share-imagebuilder-sg-{CdkUtils.stack_tag}",
            vpc=ami_share_vpc,
            allow_all_outbound=True,
            description="Security group for the EC2 Image Builder Pipeline: " + self.stack_name + "-Pipeline",
            security_group_name=f"ami-share-imagebuilder-sg-{CdkUtils.stack_tag}"
        )

        # create infrastructure configuration to supply instance type
        infra_config = imagebuilder.CfnInfrastructureConfiguration(
            self, f"ami-share-infra-config-{CdkUtils.stack_tag}",
            name=f"ami-share-infra-config-{CdkUtils.stack_tag}",
            instance_types=config["imagebuilder"]["instanceTypes"],
            instance_profile_name=instance_profile.instance_profile_name,
            subnet_id=config['vpc']['subnet_id'],
            security_group_ids=[ami_share_imagebuilder_sg.security_group_id],
            resource_tags={
                "project": "ec2-imagebuilder-ami-share"
            },
            terminate_instance_on_failure=True,
            sns_topic_arn=sns_topic.topic_arn
        )
        # infrastructure need to wait for instance profile to complete before beginning deployment.
        infra_config.add_depends_on(instance_profile)

         # recipe that installs the Ami Share components together with a Amazon Linux 2 base image
        ami_share_recipe = imagebuilder.CfnImageRecipe(
            self, f"ami-share-image-recipe-{CdkUtils.stack_tag}",
            name=f"ami-share-image-recipe-{CdkUtils.stack_tag}",
            version=config["imagebuilder"]["version"],
            components=[
                {
                    "componentArn": core.Arn.format(components=core.ArnComponents(
                        service="imagebuilder",
                        resource="component",
                        resource_name="aws-cli-version-2-linux/x.x.x",
                        account="aws"
                    ), stack=self)
                }
            ],
            parent_image=f"arn:aws:imagebuilder:{self.region}:aws:image/{config['imagebuilder']['baseImageArn']}",
            block_device_mappings=[
                imagebuilder.CfnImageRecipe.InstanceBlockDeviceMappingProperty(
                    device_name="/dev/xvda",
                    ebs=imagebuilder.CfnImageRecipe.EbsInstanceBlockDeviceSpecificationProperty(
                        delete_on_termination=True,
                        # Encryption is disabled, because the export VM doesn't support encrypted ebs
                        encrypted=False,
                        volume_size=config["imagebuilder"]["ebsVolumeSize"],
                        volume_type="gp2"
                    )
                )],
            description=f"Recipe to build and validate AmiShareImageRecipe-{CdkUtils.stack_tag}",
            tags={
                "project": "ec2-imagebuilder-ami-share"
            },
            working_directory="/imagebuilder"
        )      

        # Distribution configuration for AMIs
        ami_share_distribution_config = imagebuilder.CfnDistributionConfiguration(
            self, f'ami-share-distribution-config-{CdkUtils.stack_tag}',
            name=f'ami-share-distribution-config-{CdkUtils.stack_tag}',
            distributions=[
                imagebuilder.CfnDistributionConfiguration.DistributionProperty(
                    region=self.region,
                    ami_distribution_configuration={
                        'Name': core.Fn.sub(f'AmiShare-{CdkUtils.stack_tag}-ImageRecipe-{{{{ imagebuilder:buildDate }}}}'),
                        'AmiTags': {
                            "project": "ec2-imagebuilder-ami-share",
                            'Pipeline': f"AmiSharePipeline-{CdkUtils.stack_tag}"
                        }
                    }
                )
            ]
        )

        # build the imagebuilder pipeline
        ami_share_pipeline = imagebuilder.CfnImagePipeline(
            self, f"ami-share-pipeline-{CdkUtils.stack_tag}",
            name=f"ami-share-pipeline-{CdkUtils.stack_tag}",
            image_recipe_arn=ami_share_recipe.attr_arn,
            infrastructure_configuration_arn=infra_config.attr_arn,
            tags={
                "project": "ec2-imagebuilder-ami-share"
            },
            description=f"Image Pipeline for: AmiSharePipeline-{CdkUtils.stack_tag}",
            enhanced_image_metadata_enabled=True,
            image_tests_configuration=imagebuilder.CfnImagePipeline.ImageTestsConfigurationProperty(
                image_tests_enabled=True,
                timeout_minutes=90
            ),
            distribution_configuration_arn=ami_share_distribution_config.attr_arn,
            status="ENABLED"
        )
        ami_share_pipeline.add_depends_on(infra_config)

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
            code=aws_lambda.Code.asset("stacks/vmdkexport/resources/amidistribution"),
            handler="ami_distribution.lambda_handler",
            runtime=aws_lambda.Runtime.PYTHON_3_6,
            role=amidistribution_lambda_role,
            timeout=self.LAMBDA_TIMEOUT_DEFAULT
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


        ##########################################################
        # <START> VMDK Export
        ##########################################################        

        # Create a role for the vmdk entry point lambda function
        vmdk_entry_point_lambda_role = iam.Role(
            scope=self,
            id=f"vmdkEntryPointLambdaRole-{CdkUtils.stack_tag}",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ]
        )

        # Create vmdk entry point lambda function
        vmdk_entry_point_lambda = aws_lambda.Function(
            scope=self,
            id=f"vmdkEntryPointLambda-{CdkUtils.stack_tag}",
            code=aws_lambda.Code.asset("stacks/vmdkexport/resources/vmexport/vmdkexportentrypoint"),
            handler="vmdkexportentrypoint_function.lambda_handler",
            runtime=aws_lambda.Runtime.PYTHON_3_6,
            role=vmdk_entry_point_lambda_role,
            timeout=self.LAMBDA_TIMEOUT_DEFAULT
        )

        # Create a role for the imagebuilder poll lambda function
        imagebuilderpoll_lambda_role = iam.Role(
            scope=self,
            id=f"imageBuilderPollLambdaRole-{CdkUtils.stack_tag}",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ]
        )
        # add permissions for AMI state checking
        imagebuilderpoll_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                resources=["*"],
                actions=[
                    "imagebuilder:GetImage"
                ]
            )
        )

        # Create imagebuilder poll lambda function
        imagebuilderpoll_lambda = aws_lambda.Function(
            scope=self,
            id=f"imageBuilderPollLambda-{CdkUtils.stack_tag}",
            code=aws_lambda.Code.asset("stacks/vmdkexport/resources/vmexport/imagebuilderpoll"),
            handler="imagebuilderpoll_function.lambda_handler",
            runtime=aws_lambda.Runtime.PYTHON_3_6,
            role=imagebuilderpoll_lambda_role,
            timeout=self.LAMBDA_TIMEOUT_DEFAULT
        )

        # Create a role for the ami publish metadata lambda function
        amipublishmetadata_lambda_role = iam.Role(
            scope=self,
            id=f"amiPublishMetadataLambdaRole-{CdkUtils.stack_tag}",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ]
        )
        # add permissions for AMI metadata publishing
        amipublishmetadata_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                resources=[f"arn:aws:ssm:{core.Aws.REGION}:{core.Aws.ACCOUNT_ID}:parameter/{ami_share_pipeline.name}/{ami_share_recipe.version}/*"],
                actions=[
                    "ssm:PutParameter",
                ]
            )
        )
        # add permissions for AMI state checking
        amipublishmetadata_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                resources=["*"],
                actions=[
                    "imagebuilder:GetImage"
                ]
            )
        )

        # Create amimetadata publishing lambda function
        amipublishmetadata_lambda = aws_lambda.Function(
            scope=self,
            id=f"amiPublishMetadataLambda-{CdkUtils.stack_tag}",
            code=aws_lambda.Code.asset("stacks/vmdkexport/resources/vmexport/publishamimetadata"),
            runtime=aws_lambda.Runtime.PYTHON_3_6,
            handler="publishamimetadata_function.lambda_handler",
            role=amipublishmetadata_lambda_role,
            environment={
                "PIPELINE_NAME": ami_share_pipeline.name,
                "RECIPIE_VERSION": ami_share_recipe.version
            },
            timeout=self.LAMBDA_TIMEOUT_DEFAULT
        )

        # Role to be assumed for the VMDK export
        # This role requires a specific name; vmimport
        # As such, we use a custom resource to ensure that the role is created
        # and to prevent the CFN template from failing if the role already exists.

        # Provider that creates the role needed by the vmimport process
        # see https://docs.aws.amazon.com/vm-import/latest/userguide/vmie_prereqs.html#vmimport-role
        # see https://aws.amazon.com/premiumsupport/knowledge-center/ec2-export-vm-using-import-export/
        vmimport_role_creator_role = iam.Role(
            self, f"vmImportRoleCreatorRole-{CdkUtils.stack_tag}",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ]
        )
        # add the necessary policies to vmimport
        vmimport_role_creator_role.add_to_policy(iam.PolicyStatement(
                resources=["*"],
                actions=[
                    "iam:GetRole",
                    "iam:CreateRole",
                    "iam:TagRole"
                ]
            )   
        )
        vmimport_role_creator_lambda = aws_lambda.Function(
            scope=self,
            id=f"vmImportRoleCreatorLambda-{CdkUtils.stack_tag}",
            code=aws_lambda.Code.asset("stacks/vmdkexport/resources/vmexport/createvmimportrole"),
            handler="createvmimportrole_function.lambda_handler",
            runtime=aws_lambda.Runtime.PYTHON_3_6,
            role=vmimport_role_creator_role,
            timeout=self.LAMBDA_TIMEOUT_DEFAULT
        )
        vmimport_role_creator_provider = custom_resources.Provider(
            self, 
            f'vmImportRoleCreatorCustomResourceProvider-{CdkUtils.stack_tag}',
            on_event_handler=vmimport_role_creator_lambda
        )

        # The custom resource that uses the provider to supply values
        vmimport_role_creator_custom_resource = core.CustomResource(
            self,
            f'vmImportRoleCreatorCustomResource-{CdkUtils.stack_tag}',
            service_token=vmimport_role_creator_provider.service_token,
            properties = {
                'CdkStackName': CdkUtils.stack_tag
            }
        )

        # The result obtained from the output of custom resource
        vmimport_role_arn = core.CustomResource.get_att_string(vmimport_role_creator_custom_resource, attribute_name='Ec2VmdkImportRoleArn')

        vm_import_role = iam.Role.from_role_arn(
            self,
            f"vmdkImportRole-{CdkUtils.stack_tag}", 
            vmimport_role_arn
        )

        # add the necessary s3 policies to vmimport
        s3_bucket.grant_read_write(vm_import_role)

        # add the necessary ec2 bucket policies to vmimport
        vm_import_role.add_to_policy(iam.PolicyStatement(
            resources=["*"],
            actions=[
                "ec2:CopySnapshot",
                "ec2:Describe*",
                "ec2:ModifySnapshotAttribute",
                "ec2:RegisterImage",
                "ec2:CreateTags",
                "ec2:ExportImage"
            ]
        ))
        
        kms_key.grant_encrypt_decrypt(vm_import_role)
        kms_key.grant_encrypt_decrypt(iam.ServicePrincipal(service=f'ec2.{core.Aws.URL_SUFFIX}'))
        
        vmimport_principal = iam.PrincipalWithConditions(
            principal=iam.ServicePrincipal(f'vmie.{core.Aws.URL_SUFFIX}'),
            conditions={
                "StringEquals": {
                    "sts:ExternalId": "vmimport"
                }
            }
        )

        kms_key.grant_encrypt_decrypt(vmimport_principal)

        # Role for the vmdk export lambda
        vmdkexport_role = iam.Role(
            self, f"VmdkExportRole-{CdkUtils.stack_tag}",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ]
        )
        # add the necessary s3 policies to vmimport
        s3_bucket.grant_read_write(vmdkexport_role)

        # add the necessary ec2 bucket policies to vmimport
        vmdkexport_role.add_to_policy(iam.PolicyStatement(
            resources=["*"],
            actions=[
                "ec2:CopySnapshot",
                "ec2:Describe*",
                "ec2:ModifySnapshotAttribute",
                "ec2:RegisterImage",
                "ec2:CreateTags",
                "ec2:ExportImage"
            ]
        ))
        kms_key.grant_encrypt_decrypt(vmdkexport_role)

        # Create vmdk export lambda
        vmdkexport_lambda = aws_lambda.Function(
            scope=self,
            id=f"vmdkExportLambda-{CdkUtils.stack_tag}",
            code=aws_lambda.Code.asset("stacks/vmdkexport/resources/vmexport/vmdkexport"),
            handler="vmdkexport_function.lambda_handler",
            role=vmdkexport_role,
            runtime=aws_lambda.Runtime.PYTHON_3_6,
            environment={
                "EXPORT_BUCKET": f"{s3_bucket.bucket_name}",
                "EXPORT_ROLE": f"{vm_import_role.role_name}"
            },
            timeout=self.LAMBDA_TIMEOUT_DEFAULT
        )

        # Create a role for the vmdk completed lambda function
        vmdkcompleted_lambda_role = iam.Role(
            scope=self,
            id=f"vmdkCompletedLambdaRole-{CdkUtils.stack_tag}",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ]
        )
        # add permissions for VMDK state checking
        vmdkcompleted_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                resources=["*"],
                actions=[
                    "ec2:DescribeInstances",
                    "ec2:DescribeImages",
                    "ec2:DescribeInstanceStatus",
                    "ec2:ModifyImageAttribute",
                    "ec2:ReportInstanceStatus",
                    "ec2:DescribeExportImageTasks",
                    "ec2:DescribeExportTasks",
                    "ec2:CreateTags",
                    "ec2:ExportImage"
                ],
            )
        )

        # Create vmdkcompleted lambda function
        vmdkcompleted_lambda = aws_lambda.Function(
            scope=self,
            id=f"vmdkCompletedLambda-{CdkUtils.stack_tag}",
            code=aws_lambda.Code.asset("stacks/vmdkexport/resources/vmexport/vmdkexportcompleted"),
            handler="vmdkexportcompleted_function.lambda_handler",
            runtime=aws_lambda.Runtime.PYTHON_3_6,
            role=vmdkcompleted_lambda_role,
            timeout=self.LAMBDA_TIMEOUT_DEFAULT
        )

        # Create a role for the vmdk publish metadata lambda function
        vmdkpublishmetadata_lambda_role = iam.Role(
            scope=self,
            id=f"vdmkPublishMetadataLambdaRole-{CdkUtils.stack_tag}",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ]
        )
        # add permissions for VMDK metadata publishing
        vmdkpublishmetadata_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                resources=[f"arn:aws:ssm:{core.Aws.REGION}:{core.Aws.ACCOUNT_ID}:parameter/{ami_share_pipeline.name}/{ami_share_recipe.version}/*"],
                actions=[
                    "ssm:PutParameter"
                ]
            )
        )
        vmdkpublishmetadata_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                resources=["*"],
                actions=[
                    "ec2:DescribeExportImageTasks"
                ]
            )
        )

        sns_topic.grant_publish(vmdkpublishmetadata_lambda_role)
        kms_key.grant_encrypt_decrypt(vmdkpublishmetadata_lambda_role)

        # Create vmdk metadata publishing lambda function
        vmdkpublishmetadata_lambda = aws_lambda_python.PythonFunction(
            scope=self,
            id=f"vmdkPublishMetadataLambda-{CdkUtils.stack_tag}",
            entry="stacks/vmdkexport/resources/vmexport/publishvmdkmetadata",
            index="publishvmdkmetadata_function.py",
            handler="lambda_handler",
            runtime=aws_lambda.Runtime.PYTHON_3_6,
            role=vmdkpublishmetadata_lambda_role,
            environment={
                "PIPELINE_NAME": ami_share_pipeline.name,
                "RECIPIE_VERSION": ami_share_recipe.version,
                "SNS_TOPIC": sns_topic.topic_arn
            },
            timeout=self.LAMBDA_TIMEOUT_DEFAULT
        )

        # step function definitions
        entry_point_lambda_task = stepfunctions_tasks.LambdaInvoke(
            self, 
            "EntryPointLambdaTask", 
            input_path="$",
            output_path="$.Payload.body",
            lambda_function=vmdk_entry_point_lambda
        )

        ami_available_wait_task = stepfunctions.Wait(
            self, 
            "AMIAvailableWaitTask", 
            time=stepfunctions.WaitTime.duration(core.Duration.minutes(3))
        )

        ami_poll_lambda_task = stepfunctions_tasks.LambdaInvoke(
            self, 
            "AMIPollLambdaTask", 
            input_path="$",
            output_path="$.Payload.body",
            lambda_function=imagebuilderpoll_lambda

        )

        ami_poll_choice_task = stepfunctions.Choice(
            self,
            "AMIPollCheckTask",
            input_path="$",
            output_path="$"
        )

        ami_publish_metadata_lambda_task = stepfunctions_tasks.LambdaInvoke(
            self, 
            "AMIMetadataLambdaTask", 
            input_path="$",
            output_path="$.Payload.body",
            lambda_function=amipublishmetadata_lambda
        )

        vdmk_export_lambda_task = stepfunctions_tasks.LambdaInvoke(
            self, 
            "VDMKExportLambdaTask", 
            input_path="$",
            output_path="$.Payload.body",
            lambda_function=vmdkexport_lambda
        )

        vmdk_export_wait_task = stepfunctions.Wait(
            self, 
            "VMDKExportWaitTask", 
            time=stepfunctions.WaitTime.duration(core.Duration.minutes(3))
        )

        vmdk_poll_lambda_task = stepfunctions_tasks.LambdaInvoke(
            self, 
            "VMDKPollLambdaTask", 
            input_path="$",
            output_path="$.Payload.body",
            lambda_function=vmdkcompleted_lambda
        )

        vmdk_poll_choice_task = stepfunctions.Choice(
            self,
            "VMDKPollCheckTask",
            input_path="$",
            output_path="$"
        )

        vmdk_publish_metadata_lambda_task = stepfunctions_tasks.LambdaInvoke(
            self, 
            "VMDKMetadataLambdaTask", 
            input_path="$",
            output_path="$.Payload.body",
            lambda_function=vmdkpublishmetadata_lambda
        )

        vmdk_export_success_task = stepfunctions.Succeed(
            self, 
            "VMDKExportInvoked"
        )

        ami_poll_choice_task.when(stepfunctions.Condition.string_equals('$.ami_state', "AVAILABLE"), ami_publish_metadata_lambda_task).otherwise(ami_available_wait_task)

        ami_publish_metadata_lambda_task.next(vdmk_export_lambda_task)

        vdmk_export_lambda_task.next(vmdk_export_wait_task).next(vmdk_poll_lambda_task).next(vmdk_poll_choice_task)

        vmdk_poll_choice_task.when(stepfunctions.Condition.string_equals('$.vdmk_export_status', "COMPLETED"), vmdk_publish_metadata_lambda_task).otherwise(vmdk_export_wait_task)

        vmdk_publish_metadata_lambda_task.next(vmdk_export_success_task)

        # step functions state machine
        vmdkexport_state_machine = stepfunctions.StateMachine(
            self, f"VMDKExportStateMachine-{CdkUtils.stack_tag}",
            timeout=core.Duration.minutes(120),
            definition=entry_point_lambda_task.next(ami_available_wait_task).next(ami_poll_lambda_task).next(ami_poll_choice_task)
        )

        # Create a role for the vmdk notify lambda function
        vmdk_notify_lambda_role = iam.Role(
            scope=self,
            id=f"vmdkNotifyLambdaRole-{CdkUtils.stack_tag}",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ]
        )
        # add permissions to start step functions
        vmdk_notify_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                resources=[vmdkexport_state_machine.state_machine_arn],
                actions=[
                    "states:StartExecution"
                ]
            )
        )
        vmdk_notify_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                resources=[vmdkexport_state_machine.state_machine_arn],
                actions=[
                    "states:ListExecutions"
                ]
            )
        )

        # Create vmdk notify lambda function
        vmdk_notify_lambda = aws_lambda.Function(
            scope=self,
            id=f"vmdkNotifyLambda-{CdkUtils.stack_tag}",
            code=aws_lambda.Code.asset("stacks/vmdkexport/resources/vmexport/vmdknotify"),
            handler="vmdknotify_function.lambda_handler",
            runtime=aws_lambda.Runtime.PYTHON_3_6,
            role=vmdk_notify_lambda_role,
            environment={
                "STATE_MACHINE_ARN": vmdkexport_state_machine.state_machine_arn
            },
            timeout=self.LAMBDA_TIMEOUT_DEFAULT
        )

        # topic that triggers the VMDK export process
        vmdk_sns_topic = sns.Topic(
            self, f"VmdkNotificationTopic-{CdkUtils.stack_tag}",
            topic_name=f"VmdkNotificationTopic-{CdkUtils.stack_tag}",
            master_key=kms_key
        )

        vmdk_sns_topic.add_subscription(sns_subscriptions.LambdaSubscription(vmdk_notify_lambda))

        ##########################################################
        # </END> VMDK Export
        ##########################################################



        ##################################################
        ## <START> CDK Outputs
        ##################################################

        core.CfnOutput(
            self,
            id=f"export-pipeline-arn-{CdkUtils.stack_tag}",
            export_name=f"VmdkExport-PipelineArn-{CdkUtils.stack_tag}",
            value=ami_share_pipeline.attr_arn,
            description="Vmdk Export Pipeline Arn"
        )

        core.CfnOutput(
            self,
            id=f"export-notification-topic-arn-{CdkUtils.stack_tag}",
            export_name=f"VmdkExport-NotificationTopicArn-{CdkUtils.stack_tag}",
            value=vmdk_sns_topic.topic_arn,
            description="Vmdk Export Notification Topic Arn"
        )

        ##################################################
        ## </END> CDK Outputs
        ##################################################