##################################################
## VMDKExport entry point
## The State Machine is invoked via Lambda
## Lambda needs to receive a Http Status Code 200
## otherwise it will continue retrying the State Machine
##################################################

import json
import logging

def lambda_handler(event, context):
    # set logging
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # print the event details
    logger.debug(json.dumps(event, indent=2))

    image_build_version_arn = event["image_build_version_arn"]

    if image_build_version_arn is not None:
        return {
            'statusCode': 200,
            'body': event,
            'headers': {'Content-Type': 'application/json'}
        }
    else:
        raise ValueError("image_build_version_arn is not present in request")
