##################################################
## Notify VMDK export request
##################################################

import os
import boto3
from botocore.exceptions import ClientError
import json
import logging

def lambda_handler(event, context):
    # set logging
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # print the event details
    logger.debug(json.dumps(event, indent=2))

    # get state machine arn from env vars
    state_machine_arn = os.environ['STATE_MACHINE_ARN']

    image_build_version_arn = event["Records"][0]["Sns"]["Message"]

    stepfunctions_client = boto3.client('stepfunctions')

    response = stepfunctions_client.list_executions(
        stateMachineArn=state_machine_arn,
        statusFilter='RUNNING',
        maxResults=1000
    )

    if len(response['executions']) > 0:
        return image_build_version_arn

    response = stepfunctions_client.start_execution(
        stateMachineArn=state_machine_arn,
        input="{\"image_build_version_arn\" : \"" + image_build_version_arn + "\"}"
    )
    return image_build_version_arn