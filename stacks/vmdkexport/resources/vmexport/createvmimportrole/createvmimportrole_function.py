#!/usr/bin/env python

"""
    createvmimportrole_function.py:
    AWS Step Functions State Machine Lambda Handler which 
    creates the role required for vmimport/export operations.

    The role to be assumed for VMDK export requires a specific name; vmimport
    As such, we use a custom resource to ensure that the role is created
    and to prevent the CFN template from failing if the role already exists.

    Provider that creates the role needed by the vmimport process
    see https://docs.aws.amazon.com/vm-import/latest/userguide/vmie_prereqs.html#vmimport-role
    see https://aws.amazon.com/premiumsupport/knowledge-center/ec2-export-vm-using-import-export/
"""

import json
import logging

import boto3

# set logging
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

VM_IMPORT_ROLE_NAME = "vmimport"

client = boto3.client('iam')
iam = boto3.resource('iam')

def create_vmimport_role(cdk_stack_name):
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": { "Service": "vmie.amazonaws.com" },
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals":{
                    "sts:Externalid": "vmimport"
                    }
                }
            }
        ]
    }

    response = client.create_role(
        RoleName=VM_IMPORT_ROLE_NAME,
        AssumeRolePolicyDocument=json.dumps(trust_policy),
        Description='Role required by the VMDK export process',
        Tags=[
            {
                'Key': 'CDK/StackClass',
                'Value': cdk_stack_name
            },
            {
                'Key': 'Project',
                'Value': 'SiemensStarCCM'
            }
        ]
    )

    logger.info(f"Created new role for {iam.Role(VM_IMPORT_ROLE_NAME).role_name}")
    return response['Role']['Arn']

def lambda_handler(event, context):
    # set logging
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # print the event details
    logger.debug(json.dumps(event, indent=2))

    props = event['ResourceProperties']
    cdk_stack_name = props['CdkStackName']

    if event['RequestType'] != 'Delete':
        try:
            response = client.get_role(
                RoleName=VM_IMPORT_ROLE_NAME
            )
            role_arn = response['Role']['Arn']
            output = {
                'PhysicalResourceId': f"ec2-vmimport-role-{cdk_stack_name}",
                'Data': {
                    'Ec2VmdkImportRoleArn': role_arn
                }
            }
            logger.info("Output: " + json.dumps(output))
            return output
        except client.exceptions.NoSuchEntityException:
            logger.info(f"{VM_IMPORT_ROLE_NAME} not found. Adding role.")
            # add the role and policy
            logger.info(f"Adding role {VM_IMPORT_ROLE_NAME}")
            role_arn = create_vmimport_role(cdk_stack_name)
            output = {
                'PhysicalResourceId': f"ec2-vmimport-role-{cdk_stack_name}",
                'Data': {
                    'Ec2VmdkImportRoleArn': role_arn
                }
            }
            logger.info("Output: " + json.dumps(output))
            return output
