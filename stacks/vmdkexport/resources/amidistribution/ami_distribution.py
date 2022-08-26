#!/usr/bin/env python

"""
    ami_distribution.py:
    CloudFormation Custom Resource Hanlder used to configure the
    AMI distribution targets of the EC2 Image Builder instance
    created by CDK.
    
    EC2 ImageBuilder AMI distribution setting targetAccountIds
    is not supported by CloudFormation (as of September 2021).
    https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-imagebuilder-distributionconfiguration.html
    This lambda function uses Boto3 for EC2 ImageBuilder in order 
    to set the AMI distribution settings which are currently missing from 
    CloudFormation - specifically the targetAccountIds attribute
    https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/imagebuilder.html
"""


import json
import logging
import os

import boto3
import botocore


def get_ssm_parameter(
        ssm_param_name: str, 
        aws_ssm_region: str
    ) -> str:
    ssm = boto3.client('ssm', region_name=aws_ssm_region)
    parameter = ssm.get_parameter(Name=ssm_param_name, WithDecryption=False)
    return parameter['Parameter']


def get_distributions_configurations(
        aws_distribution_regions: list[str],
        ami_distribution_name: str,
        publishing_account_ids: list[str],
        sharing_account_ids: list[str]
    ) -> list[dict]:

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
            client.update_distribution_configuration(
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
    logger.info(f"Output: {json.dumps(output)}")
    return output
