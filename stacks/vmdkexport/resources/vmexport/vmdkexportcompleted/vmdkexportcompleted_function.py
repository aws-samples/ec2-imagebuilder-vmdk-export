#!/usr/bin/env python

"""
    vmdkexportcompleted_function.py:
    AWS Step Functions State Machine Lambda Handler which 
    polls the VMImport/Export service in order to determine
    when an export job has completed.
"""

import json
import logging

import boto3


def lambda_handler(event, context):
    # set logging
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    
    # print the event details
    logger.debug(json.dumps(event, indent=2))

    # grab the event details
    export_image_task_id = event["export_image_task_id"]

    logger.debug(f"export_image_task_id = {export_image_task_id}")

    # check if the ami export is in the completed state
    ec2_client = boto3.client('ec2')
    response = ec2_client.describe_export_image_tasks(
        ExportImageTaskIds=[
            export_image_task_id
        ]
    )

    logger.info(f"Checking if AMI export is in completed state")
    
    # return a NOT_COMPLETED state if the ami export is not completed
    vdmk_export_status = "NOT_COMPLETED"

    if len(response['ExportImageTasks']) > 0:
        for export_task in response['ExportImageTasks']:
            if export_task['ExportImageTaskId'] == export_image_task_id:
                logger.info(f"Got task id match: {export_task['ExportImageTaskId']}")
                vdmk_export_status = str(export_task['Status']).upper()
                logger.info(f"Current AMI export state: {vdmk_export_status}")
                break

    logger.info(f"Returning vdmk_export_status: {vdmk_export_status}")

    event["vdmk_export_status"] = vdmk_export_status
    
    return {
        'statusCode': 200,
        'body': event,
        'headers': {'Content-Type': 'application/json'}
    }
