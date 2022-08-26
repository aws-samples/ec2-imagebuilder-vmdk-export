#!/usr/bin/env python

"""
    vmdkexport_function.py:
    AWS Step Functions State Machine Lambda Handler which 
    executes the VMExport process in order to export an
    AMI to VMDK format.
"""

import json
import logging
import os

import boto3


def lambda_handler(event, context):
    # set logging
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    
    # print the event details
    logger.debug(json.dumps(event, indent=2))

    # get env vars
    export_bucket = os.environ['EXPORT_BUCKET']
    export_role = os.environ['EXPORT_ROLE']

    # grab the event parameters
    ami_id = event["ami_id"]
    ami_name = event["ami_name"]
    logger.debug(f"ami_id = {ami_id}")
    logger.debug(f"ami_name = {ami_name}")

    # export the ami image to vmdk
    ec2_client = boto3.client('ec2')
    response = ec2_client.export_image(
        DiskImageFormat='VMDK',
        ImageId=ami_id,
        S3ExportLocation={
            'S3Bucket': export_bucket,
            'S3Prefix': 'exports/'
        },
        RoleName=export_role
    )

    logger.info(f"Image {ami_id} is being exported to s3 bucket {export_bucket}/exports")
    logger.info(f"Export image task id: {response['ExportImageTaskId']}")

    event["export_image_task_id"] = response['ExportImageTaskId']
    
    return {
        'statusCode': 200,
        'body': event,
        'headers': {'Content-Type': 'application/json'}
    }
