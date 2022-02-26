import json

import pytest
from expects import expect

from aws_cdk import (
    core
)

from cdk_expects_matcher.CdkMatchers import have_resource, ANY_VALUE, contain_metadata_path
import tests.utils.base_test_case as tc
from stacks.vmdkexport.vmdk_export import VmdkExportStack
from utils.CdkUtils import CdkUtils


@pytest.fixture(scope="class")
def vmdk_export_stack_main(request):
    request.cls.cfn_template = tc.BaseTestCase.load_stack_template(VmdkExportStack.__name__)


@pytest.mark.usefixtures('synth', 'vmdk_export_stack_main')
class TestVmdkExportStack(tc.BaseTestCase):
    """
        Test case for VmdkExportStack
    """

    config = CdkUtils.get_project_settings()

    ##################################################
    ## <START> EC2 Security Group tests
    ##################################################
    def test_no_admin_permissions(self):
        assert json.dumps(self.cfn_template).count(':iam::aws:policy/AdministratorAccess') == 0

    def test_ami_share_imagebuilder_instance_profile_created(self):
        expect(self.cfn_template).to(
            contain_metadata_path(self.iam_instance_profile, f"ami-share-imagebuilder-instance-profile-{CdkUtils.stack_tag}"
            )
        )

    def test_ami_share_security_group_created(self):
        expect(self.cfn_template).to(
            contain_metadata_path(self.ec2_security_group, f"ami-share-imagebuilder-sg-{CdkUtils.stack_tag}")
        )

    def test_ami_share_image_role_created(self):
        expect(self.cfn_template).to(
            contain_metadata_path(self.iam_role, f"ami-share-image-role-{CdkUtils.stack_tag}")
        )

    def test_ami_share_image_role_policy(self):
        expect(self.cfn_template).to(have_resource(
            self.iam_role,
            {
                "AssumeRolePolicyDocument": {
                    "Statement": [
                        {
                            "Action": "sts:AssumeRole",
                            "Effect": "Allow",
                            "Principal": {
                                "Service": "ec2.amazonaws.com"
                            }
                        }
                    ],
                    "Version": "2012-10-17"
                },
                "ManagedPolicyArns": [
                    {
                        "Fn::Join": [
                            "",
                            [
                                "arn:",
                                {
                                    "Ref": "AWS::Partition"
                                },
                                ":iam::aws:policy/AmazonSSMManagedInstanceCore"
                            ]
                        ]
                    },
                    {
                        "Fn::Join": [
                            "",
                            [
                                "arn:",
                                {
                                    "Ref": "AWS::Partition"
                                },
                                ":iam::aws:policy/EC2InstanceProfileForImageBuilder"
                            ]
                        ]
                    }
                ]
            }
        ))
    ##################################################
    ## </END> EC2 Security Group tests
    ##################################################

    ##################################################
    ## <START> KMS tests
    ##################################################
    def test_ami_share_kms_key_rotation_created(self):
        expect(self.cfn_template).to(have_resource(self.kms_key, {
            "EnableKeyRotation": True
        }))

    def test_ami_share_kms_key_alias_created(self):
        expect(self.cfn_template).to(have_resource(self.kms_alias, {
            "AliasName": f"alias/ami-share-kms-key-alias-{CdkUtils.stack_tag}"
        }))

    def test_ami_share_kms_key_created(self):
        expect(self.cfn_template).to(
            contain_metadata_path(self.kms_key, f"ami-share-kms-key-{CdkUtils.stack_tag}"
            )
        )
    ##################################################
    ## </END> AWS KMS tests
    ##################################################

    ##################################################
    ## <START> EC2 Imagebuilder tests
    ##################################################
    def test_infra_config_created(self):
        expect(self.cfn_template).to(contain_metadata_path(
            self.imagebuilder_infrastructure_configuration, f"ami-share-infra-config-{CdkUtils.stack_tag}"
            )
        )
    
    def test_ami_share_recipe_created(self):
        expect(self.cfn_template).to(contain_metadata_path(
            self.imagebuilder_recipe, f"ami-share-image-recipe-{CdkUtils.stack_tag}"
            )
        )

    def test_ami_share_pipeline_created(self):
        expect(self.cfn_template).to(
            contain_metadata_path(self.imagebuilder_image_pipeline, f"ami-share-pipeline-{CdkUtils.stack_tag}"
            )
        )

    def test_ami_share_distribution_config(self):
        expect(self.cfn_template).to(
            have_resource(self.imagebuilder_distribution_config, {
                "Distributions": [
                    {
                        "AmiDistributionConfiguration": {
                            "Name": {
                                "Fn::Sub": f'AmiShare-{CdkUtils.stack_tag}-ImageRecipe-{{{{ imagebuilder:buildDate }}}}'
                            },
                            "AmiTags": {
                                "project": "ec2-imagebuilder-ami-share",
                            "Pipeline": f"AmiSharePipeline-{CdkUtils.stack_tag}"
                            }
                        },
                        "Region": core.Aws.REGION
                    }
                ],
                "Name": f'ami-share-distribution-config-{CdkUtils.stack_tag}'
            }))

    def test_sns_topic_created(self):
        expect(self.cfn_template).to(
            contain_metadata_path(self.sns_topic, f"ami-share-imagebuilder-topic-{CdkUtils.stack_tag}"))

    def test_sns_subscription_created(self):
        expect(self.cfn_template).to(
            have_resource(self.sns_subscription,
                          {
                              "Protocol": "email",
                              "TopicArn": {
                                  "Ref": ANY_VALUE
                              },
                              "Endpoint": ANY_VALUE
                          },
                          )
        )
    ##################################################
    ## </END> EC2 Imagebuilder tests
    ##################################################

    ##################################################
    ## <START> AWS Custom resource tests
    ##################################################

    def test_ami_distribution_custom_resource_created(self):
        expect(self.cfn_template).to(contain_metadata_path(self.custom_cfn_resource, f'AmiDistributionCustomResource-{CdkUtils.stack_tag}'))

    def test_ami_distribution_lambda(self):
        expect(self.cfn_template).to(contain_metadata_path(self.lambda_, f'amiDistributionLambda-{CdkUtils.stack_tag}'))

    def test_ami_distribution_policy_role(self):
        expect(self.cfn_template).to(have_resource(
            self.iam_role,
            {
                "AssumeRolePolicyDocument": {
                    "Statement": [
                        {
                            "Action": "sts:AssumeRole",
                            "Effect": "Allow",
                            "Principal": {
                                "Service": "lambda.amazonaws.com"
                            }
                        }
                    ],
                    "Version": "2012-10-17"
                },
                "ManagedPolicyArns": [
                    {
                        "Fn::Join": [
                            "",
                            [
                                "arn:",
                                {
                                    "Ref": "AWS::Partition"
                                },
                                ":iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
                            ]
                        ]
                    }
                ]
            }
        ))

    def test_ami_distribution_policy(self):
        expect(self.cfn_template).to(have_resource(
            self.iam_policy,
            {
                "PolicyDocument": {
                    "Statement": [
                        {
                            "Action": "imagebuilder:UpdateDistributionConfiguration",
                            "Effect": "Allow",
                            "Resource": {
                                "Fn::GetAtt": [
                                    "AmiDistributionConfig",
                                    "Arn"
                                ]
                            }
                        }
                    ]
                }
            }
        ))

    ##################################################
    ## </END> AWS Custom resource tests
    ##################################################

    def test_vmimport_role_creator_lambda(self):
        expect(self.cfn_template).to(contain_metadata_path(self.lambda_, f"vmImportRoleCreatorLambda-{CdkUtils.stack_tag}"))

    def test_vmimport_role_creator_lambda_role(self):
         expect(self.cfn_template).to(
         contain_metadata_path(self.iam_role,f"vmImportRoleCreatorRole-{CdkUtils.stack_tag}"))

    def test_vmimport_role_creator_lambda_policy_role(self):
        expect(self.cfn_template).to(have_resource(
            self.iam_policy,
            {
                "PolicyDocument": {
                    "Statement": [
                        {
                            "Action": [
                                "iam:GetRole",
                                "iam:CreateRole"
                            ],
                            "Effect": "Allow",
                            "Resource": "*"
                        }
                    ]
                }
            }
        ))

    def test_vmdkexport_lambda(self):
        expect(self.cfn_template).to(contain_metadata_path(self.lambda_, f"vmdkExportLambda-{CdkUtils.stack_tag}"))

    def test_vmdkexport_lambda_role(self):
         expect(self.cfn_template).to(
         contain_metadata_path(self.iam_role,f"VmdkExportRole-{CdkUtils.stack_tag}"))

    def test_vmdkexport_policy_role(self):
        expect(self.cfn_template).to(have_resource(
            self.iam_policy,
            {
                "PolicyDocument": {
                    "Statement": [
                        {
                            "Action": [
                                "ec2:CopySnapshot",
                                "ec2:Describe*",
                                "ec2:ModifySnapshotAttribute",
                                "ec2:RegisterImage",
                                "ec2:CreateTags",
                                "ec2:ExportImage"
                            ],
                            "Effect": "Allow",
                            "Resource": "*"
                        }
                    ]
                }
            }
        ))

    def test_vmdkcompleted_lambda(self):
        expect(self.cfn_template).to(contain_metadata_path(self.lambda_, f"vmdkCompletedLambda-{CdkUtils.stack_tag}"))

    def test_vmdkcompleted_lambda_role(self):
         expect(self.cfn_template).to(
         contain_metadata_path(self.iam_role,f"vmdkCompletedLambdaRole-{CdkUtils.stack_tag}"))

    def test_vmdkcompleted_policy_role(self):
        expect(self.cfn_template).to(have_resource(
            self.iam_policy,
            {
                "PolicyDocument": {
                    "Statement": [
                        {
                            "Action": [
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
                            "Effect": "Allow",
                            "Resource": "*"
                        }
                    ]
                }
            }
        ))

    def test_vmdk_metadata_publish_lambda(self):
        expect(self.cfn_template).to(contain_metadata_path(self.lambda_, f"vmdkPublishMetadataLambda-{CdkUtils.stack_tag}"))

    def test_vmdk_metadata_publish_lambda_role(self):
         expect(self.cfn_template).to(
         contain_metadata_path(self.iam_role,f"vdmkPublishMetadataLambdaRole-{CdkUtils.stack_tag}"))

    def test_vmdk_notify_lambda(self):
        expect(self.cfn_template).to(contain_metadata_path(self.lambda_, f"vmdkNotifyLambda-{CdkUtils.stack_tag}"))

    def test_vmdk_notify_lambda_role(self):
         expect(self.cfn_template).to(
         contain_metadata_path(self.iam_role,f"vmdkNotifyLambdaRole-{CdkUtils.stack_tag}"))

    def test_ami_distribution_custom_resource_created(self):
        expect(self.cfn_template).to(contain_metadata_path(self.custom_cfn_resource, f'vmImportRoleCreatorCustomResource-{CdkUtils.stack_tag}'))
        
    def test_vmdkcompleted_lambda_role(self):
         expect(self.cfn_template).to(
         contain_metadata_path(self.state_machine,f"VMDKExportStateMachine-{CdkUtils.stack_tag}"))