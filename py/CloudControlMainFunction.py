"""Main Lambda function"""

import json
#import os
import logging
import random
from typing import (
    Union,
    Dict,
    Any,
    List)
import boto3
import requests
import six

import base64

from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.dispatch_components import (
    AbstractRequestHandler,
    AbstractExceptionHandler,
    AbstractResponseInterceptor,
    AbstractRequestInterceptor)
from ask_sdk_core.utils import (
    is_request_type,
    is_intent_name)
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model.ui import SimpleCard
from ask_sdk_model.dialog import (
    ElicitSlotDirective, DelegateDirective)
from ask_sdk_model import (
    Response,
    IntentRequest,
    DialogState,
    SlotConfirmationStatus,
    Slot)
from ask_sdk_model.slu.entityresolution import StatusCode

sb = SkillBuilder()

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

ec2 = boto3.client('ec2')
ec2_action = boto3.resource('ec2')
cloudwatch = boto3.client('cloudwatch')
lambda_invoke = boto3.client('lambda')

# Functions

def get_slot_values(filled_slots):
    """Return slot values with additional info."""
    slot_values = {}

    for key, slot_item in six.iteritems(filled_slots):
        name = slot_item.name
        try:
            status_code = slot_item.resolutions.resolutions_per_authority[0].status.code

            if status_code == StatusCode.ER_SUCCESS_MATCH:
                slot_values[name] = {
                    "synonym": slot_item.value,
                    "resolved": slot_item.resolutions.resolutions_per_authority[0].values[0].value.name,
                    "is_validated": True,
                }
            elif status_code == StatusCode.ER_SUCCESS_NO_MATCH:
                slot_values[name] = {
                    "synonym": slot_item.value,
                    "resolved": slot_item.value,
                    "is_validated": False,
                }
            else:
                pass
        except (AttributeError, ValueError, KeyError, IndexError, TypeError) as e:
            logger.info("Couldn't resolve status_code for slot item: {}".format(slot_item))
            logger.info(e)
            slot_values[name] = {
                "synonym": slot_item.value,
                "resolved": slot_item.value,
                "is_validated": False,
            }
    return slot_values

# Default classes

class LaunchRequestHandler(AbstractRequestHandler):
    """Handler for Skill Launch."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        speech_text = "Hello, Cloud Control is waiting for your instructions."
        reprompt = "Please, select the service to manage."

        handler_input.response_builder.speak(speech_text).ask(reprompt).set_card(
            SimpleCard("Cloud Control", speech_text)).set_should_end_session(
                False)
        return handler_input.response_builder.response

class HelpIntentHandler(AbstractRequestHandler):
    """Handler for Help Intent."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        speech_text = "I'm Cloud Control. By using proper command you can \
            manage AWS EC2 resources."

        handler_input.response_builder.speak(speech_text).ask(
            speech_text).set_card(SimpleCard(
                "Cloud Control", speech_text))
        return handler_input.response_builder.response

class CancelOrStopIntentHandler(AbstractRequestHandler):
    """Single handler for Cancel and Stop Intent."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (is_intent_name("AMAZON.CancelIntent")(handler_input) or
                is_intent_name("AMAZON.StopIntent")(handler_input))

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        speech_text = "Goodbye!"

        handler_input.response_builder.speak(speech_text).set_card(
            SimpleCard("Cloud Control", speech_text))
        return handler_input.response_builder.response

class FallbackIntentHandler(AbstractRequestHandler):
    """AMAZON.FallbackIntent is only available in en-US locale.
    This handler will not be triggered except in that locale,
    so it is safe to deploy on any locale.
    """
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_intent_name("AMAZON.FallbackIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        speech_text = (
            "I cannot comply. "
            "Please, rephrase your statement.")
        reprompt = "does not compute!"
        handler_input.response_builder.speak(speech_text).ask(reprompt)
        return handler_input.response_builder.response

class SessionEndedRequestHandler(AbstractRequestHandler):
    """Handler for Session End."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_request_type("SessionEndedRequest")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        return handler_input.response_builder.response

class CatchAllExceptionHandler(AbstractExceptionHandler):
    """Catch all exception handler, log exception and
    respond with custom message.
    """
    def can_handle(self, handler_input, exception):
        # type: (HandlerInput, Exception) -> bool
        return True

    def handle(self, handler_input, exception):
        # type: (HandlerInput, Exception) -> Response
        logger.error(exception, exc_info=True)

        speech = "Does not compute!"
        handler_input.response_builder.speak(speech).ask(speech)

        return handler_input.response_builder.response

# Custom classes

# Create instance classes
class InProgressEcCreateIntentHandler(AbstractRequestHandler):
    """Create Instance in progress"""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (is_intent_name("EcCreateIntentHandler")(handler_input)
                and handler_input.request_envelope.request.dialog_state != DialogState.COMPLETED)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In InProgressEcCreateIntent")
        current_intent = handler_input.request_envelope.request.intent
        prompt = ""

        for slot_name, current_slot in six.iteritems(current_intent.slots):
            if slot_name in ["EcInstanceSgSelector", "EcInstanceKeySelector",
                             "EcInstanceNameSelector", "EcInstanceTypeSelector",
                             "EcInstanceSubnetSelector"]:
                if (current_slot.confirmation_status != SlotConfirmationStatus.CONFIRMED
                        and current_slot.resolutions
                        and current_slot.resolutions.resolutions_per_authority[0]):
                    if current_slot.resolutions.resolutions_per_authority[0].status.code == StatusCode.ER_SUCCESS_MATCH:
                        if len(current_slot.resolutions.resolutions_per_authority[0].values) > 1:
                            prompt = "Select "

                            values = " or ".join([e.value.name for e in current_slot.resolutions.resolutions_per_authority[0].values])
                            prompt += values + " ?"
                            return handler_input.response_builder.speak(
                                prompt).ask(prompt).add_directive(
                                    ElicitSlotDirective(slot_to_elicit=current_slot.name)
                                    ).response
                    elif current_slot.resolutions.resolutions_per_authority[0].status.code == StatusCode.ER_SUCCESS_NO_MATCH:
                        if current_slot.name in required_slots:
                            prompt = "What {} are you looking for?".format(current_slot.name)

                            return handler_input.response_builder.speak(
                                prompt).ask(prompt).add_directive(
                                    ElicitSlotDirective(
                                        slot_to_elicit=current_slot.name
                                    )).response

        return handler_input.response_builder.add_directive(
            DelegateDirective(
                updated_intent=current_intent
            )).response

class CompletedEcCreateIntentHandler(AbstractRequestHandler):
    """Create Instance completed"""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (is_intent_name("EcCreateIntent")(handler_input)
                and handler_input.request_envelope.request.dialog_state == DialogState.COMPLETED)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In CompletedEcCreateIntent")
        filled_slots = handler_input.request_envelope.request.intent.slots
        slot_values = get_slot_values(filled_slots)

        try:
            # create list of values
            ec2_instance_payload = [
                slot_values["EcInstanceNameSelector"]["resolved"].replace(" ", "-"),
                slot_values["EcInstanceSubnetSelector"]["resolved"].replace(" ", "-").replace(".", "").lower(),
                slot_values["EcInstanceSgSelector"]["resolved"].replace(" ", "-"),
                slot_values["EcInstanceTypeSelector"]["resolved"].replace(" ", "."),
                slot_values["EcInstanceKeySelector"]["resolved"].replace(" ", "-")
            ]
            # log payload for ec2 create process
            #logger.info('\n'.join(map(str, ec2_instance_payload)))
            success_code, msg = ec_create(ec2_instance_payload)
            speech = msg

        except Exception as e:
            speech = ("I am really sorry. I am unable to access part of my "
                      "memory. Please try again later")
            logger.info("Intent: {}: message: {}".format(
                handler_input.request_envelope.request.intent.name, str(e)))

        reprompt = "I am waiting for new instruction."
        handler_input.response_builder.speak(speech).ask(reprompt).set_card(
            SimpleCard("Cloud Control", speech)).set_should_end_session(
                False)

        return handler_input.response_builder.speak(speech).response

# Terminate instance(s) classes
class InProgressEcTerminateIntentHandler(AbstractRequestHandler):
    """Terminate Instance(s) in progress"""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (is_intent_name("EcTerminateIntentHandler")(handler_input)
                and handler_input.request_envelope.request.dialog_state != DialogState.COMPLETED)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In InProgressEcTerminateIntent")
        current_intent = handler_input.request_envelope.request.intent
        prompt = ""

        for slot_name, current_slot in six.iteritems(current_intent.slots):
            if slot_name in ["EcInstanceNameSelector"]:
                if (current_slot.confirmation_status != SlotConfirmationStatus.CONFIRMED
                        and current_slot.resolutions
                        and current_slot.resolutions.resolutions_per_authority[0]):
                    if current_slot.resolutions.resolutions_per_authority[0].status.code == StatusCode.ER_SUCCESS_MATCH:
                        if len(current_slot.resolutions.resolutions_per_authority[0].values) > 1:
                            prompt = "Select "

                            values = " or ".join([e.value.name for e in current_slot.resolutions.resolutions_per_authority[0].values])
                            prompt += values + " ?"
                            return handler_input.response_builder.speak(
                                prompt).ask(prompt).add_directive(
                                    ElicitSlotDirective(slot_to_elicit=current_slot.name)
                                    ).response
                    elif current_slot.resolutions.resolutions_per_authority[0].status.code == StatusCode.ER_SUCCESS_NO_MATCH:
                        if current_slot.name in required_slots:
                            prompt = "What {} are you looking for?".format(current_slot.name)

                            return handler_input.response_builder.speak(
                                prompt).ask(prompt).add_directive(
                                    ElicitSlotDirective(
                                        slot_to_elicit=current_slot.name
                                    )).response

        return handler_input.response_builder.add_directive(
            DelegateDirective(
                updated_intent=current_intent
            )).response

class CompletedEcTerminateIntentHandler(AbstractRequestHandler):
    """Terminate Instance(s) completed"""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (is_intent_name("EcTerminateIntent")(handler_input)
                and handler_input.request_envelope.request.dialog_state == DialogState.COMPLETED)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In CompletedEcTerminateIntent")
        filled_slots = handler_input.request_envelope.request.intent.slots
        slot_values = get_slot_values(filled_slots)

        try:
            # create list of values
            ec2_instance_payload = [
                slot_values["EcInstanceNameSelector"]["resolved"].replace(" ", "-")]
            success_code, msg = ec_terminate(ec2_instance_payload)
            speech = msg

        except Exception as e:
            speech = ("I am really sorry. I am unable to access part of my "
                      "memory. Please try again later")
            logger.info("Intent: {}: message: {}".format(
                handler_input.request_envelope.request.intent.name, str(e)))

        reprompt = "I am waiting for new instruction."
        handler_input.response_builder.speak(speech).ask(reprompt).set_card(
            SimpleCard("Cloud Control", speech)).set_should_end_session(
                False)

        return handler_input.response_builder.speak(speech).response

# Start/stop/restart/hibernate instance classes
class InProgressEcActionStateIntentHandler(AbstractRequestHandler):
    """Start/stop/restart/hibernate instance in progress"""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (is_intent_name("EcActionStateIntentHandler")(handler_input)
                and handler_input.request_envelope.request.dialog_state != DialogState.COMPLETED)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In InProgressEcActionStateIntent")
        current_intent = handler_input.request_envelope.request.intent
        prompt = ""

        for slot_name, current_slot in six.iteritems(current_intent.slots):
            if slot_name in ["EcInstanceNameSelector", "EcActionStateSelector"]:
                if (current_slot.confirmation_status != SlotConfirmationStatus.CONFIRMED
                        and current_slot.resolutions
                        and current_slot.resolutions.resolutions_per_authority[0]):
                    if current_slot.resolutions.resolutions_per_authority[0].status.code == StatusCode.ER_SUCCESS_MATCH:
                        if len(current_slot.resolutions.resolutions_per_authority[0].values) > 1:
                            prompt = "Select "

                            values = " or ".join([e.value.name for e in current_slot.resolutions.resolutions_per_authority[0].values])
                            prompt += values + " ?"
                            return handler_input.response_builder.speak(
                                prompt).ask(prompt).add_directive(
                                    ElicitSlotDirective(slot_to_elicit=current_slot.name)
                                    ).response
                    elif current_slot.resolutions.resolutions_per_authority[0].status.code == StatusCode.ER_SUCCESS_NO_MATCH:
                        if current_slot.name in required_slots:
                            prompt = "What {} are you looking for?".format(current_slot.name)

                            return handler_input.response_builder.speak(
                                prompt).ask(prompt).add_directive(
                                    ElicitSlotDirective(
                                        slot_to_elicit=current_slot.name
                                    )).response

        return handler_input.response_builder.add_directive(
            DelegateDirective(
                updated_intent=current_intent
            )).response

class CompletedEcActionStateIntentHandler(AbstractRequestHandler):
    """Start/stop/restart/hibernate instance completed"""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (is_intent_name("EcActionStateIntent")(handler_input)
                and handler_input.request_envelope.request.dialog_state == DialogState.COMPLETED)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In CompletedEcActionStateIntent")
        filled_slots = handler_input.request_envelope.request.intent.slots
        slot_values = get_slot_values(filled_slots)

        try:
            # create list of values
            ec2_instance_payload = [
                slot_values["EcInstanceNameSelector"]["resolved"].replace(" ", "-"),
                slot_values["EcActionStateSelector"]["resolved"]]
            lambda_payload = {"body": {
                "InstanceName": ec2_instance_payload[0],
                "InstanceState": ec2_instance_payload[1]}
            }
            response = lambda_invoke.invoke(
                FunctionName='CloudControlStateActionEc2',
                InvocationType='RequestResponse',
                LogType='None',
                Payload=json.dumps(lambda_payload)
            )
            returned_data = response['Payload'].read().decode()
            data = json.loads(returned_data)
            logger.info(msg)
            speech = data[1]["msg"]

        except Exception as e:
            speech = ("I am sorry, something went wrong... I am off, man...")
            logger.info("Intent: {}: message: {}".format(
                handler_input.request_envelope.request.intent.name, str(e)))

        reprompt = "I am waiting for new instruction."
        handler_input.response_builder.speak(speech).ask(reprompt).set_card(
            SimpleCard("Cloud Control", speech)).set_should_end_session(
                False)

        return handler_input.response_builder.speak(speech).response

# Ec2 Tags - create, remove and update classes
class InProgressEcTagIntentHandler(AbstractRequestHandler):
    """Ec2 tags - create, update, remove in progress"""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (is_intent_name("EcTagIntentHandler")(handler_input)
                and handler_input.request_envelope.request.dialog_state != DialogState.COMPLETED)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In InProgressEcTagIntent")
        current_intent = handler_input.request_envelope.request.intent
        prompt = ""

        for slot_name, current_slot in six.iteritems(current_intent.slots):
            if slot_name in ["EcInstanceNameSelector",
                             "EcTagActionSelector",
                             "EcTagKeySelector",
                             "EcTagValueSelector"]:
                if (current_slot.confirmation_status != SlotConfirmationStatus.CONFIRMED
                        and current_slot.resolutions
                        and current_slot.resolutions.resolutions_per_authority[0]):
                    if current_slot.resolutions.resolutions_per_authority[0].status.code == StatusCode.ER_SUCCESS_MATCH:
                        if len(current_slot.resolutions.resolutions_per_authority[0].values) > 1:
                            prompt = "Select "

                            values = " or ".join([e.value.name for e in current_slot.resolutions.resolutions_per_authority[0].values])
                            prompt += values + " ?"
                            return handler_input.response_builder.speak(
                                prompt).ask(prompt).add_directive(
                                    ElicitSlotDirective(slot_to_elicit=current_slot.name)
                                    ).response
                    elif current_slot.resolutions.resolutions_per_authority[0].status.code == StatusCode.ER_SUCCESS_NO_MATCH:
                        if current_slot.name in required_slots:
                            prompt = "What {} are you looking for?".format(current_slot.name)

                            return handler_input.response_builder.speak(
                                prompt).ask(prompt).add_directive(
                                    ElicitSlotDirective(
                                        slot_to_elicit=current_slot.name
                                    )).response

        return handler_input.response_builder.add_directive(
            DelegateDirective(
                updated_intent=current_intent
            )).response

class CompletedEcTagIntentHandler(AbstractRequestHandler):
    """Create, remove, update instance tag completed"""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (is_intent_name("EcTagIntent")(handler_input)
                and handler_input.request_envelope.request.dialog_state == DialogState.COMPLETED)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In CompletedEcTagIntent")
        filled_slots = handler_input.request_envelope.request.intent.slots
        slot_values = get_slot_values(filled_slots)

        try:
            # create list of values
            ec2_instance_payload = [
                slot_values["EcInstanceNameSelector"]["resolved"].replace(" ", "-"),
                slot_values["EcTagActionSelector"]["resolved"],
                slot_values["EcTagKeySelector"]["resolved"].replace(" ", "-"),
                slot_values["EcTagValueSelector"]["resolved"].replace(" ", "-")]
            success_code, msg = ec_tag_action(ec2_instance_payload)
            speech = msg

        except Exception as e:
            speech = ("I am sorry, something went wrong...")
            logger.info("Intent: {}: message: {}".format(
                handler_input.request_envelope.request.intent.name, str(e)))

        reprompt = "I am waiting for new instruction."
        handler_input.response_builder.speak(speech).ask(reprompt).set_card(
            SimpleCard("Cloud Control", speech)).set_should_end_session(
                False)

        return handler_input.response_builder.speak(speech).response

# List all tags for instance classes
class InProgressEcDescribeTagsIntentHandler(AbstractRequestHandler):
    """List all tags for instance in progress"""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (is_intent_name("EcDescribeTagsIntentHandler")(handler_input)
                and handler_input.request_envelope.request.dialog_state != DialogState.COMPLETED)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In InProgressEcDescribeTagsIntent")
        current_intent = handler_input.request_envelope.request.intent
        prompt = ""

        for slot_name, current_slot in six.iteritems(current_intent.slots):
            if slot_name in ["EcInstanceNameSelector"]:
                if (current_slot.confirmation_status != SlotConfirmationStatus.CONFIRMED
                        and current_slot.resolutions
                        and current_slot.resolutions.resolutions_per_authority[0]):
                    if current_slot.resolutions.resolutions_per_authority[0].status.code == StatusCode.ER_SUCCESS_MATCH:
                        if len(current_slot.resolutions.resolutions_per_authority[0].values) > 1:
                            prompt = "Select "

                            values = " or ".join([e.value.name for e in current_slot.resolutions.resolutions_per_authority[0].values])
                            prompt += values + " ?"
                            return handler_input.response_builder.speak(
                                prompt).ask(prompt).add_directive(
                                    ElicitSlotDirective(slot_to_elicit=current_slot.name)
                                    ).response
                    elif current_slot.resolutions.resolutions_per_authority[0].status.code == StatusCode.ER_SUCCESS_NO_MATCH:
                        if current_slot.name in required_slots:
                            prompt = "What {} are you looking for?".format(current_slot.name)

                            return handler_input.response_builder.speak(
                                prompt).ask(prompt).add_directive(
                                    ElicitSlotDirective(
                                        slot_to_elicit=current_slot.name
                                    )).response

        return handler_input.response_builder.add_directive(
            DelegateDirective(
                updated_intent=current_intent
            )).response

class CompletedEcDescribeTagsIntentHandler(AbstractRequestHandler):
    """Create, remove, update instance tag completed"""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (is_intent_name("EcDescribeTagsIntent")(handler_input)
                and handler_input.request_envelope.request.dialog_state == DialogState.COMPLETED)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In CompletedDescribeTagsIntent")
        filled_slots = handler_input.request_envelope.request.intent.slots
        slot_values = get_slot_values(filled_slots)

        try:
            # create list of values
            ec2_instance_payload = [
                slot_values["EcInstanceNameSelector"]["resolved"].replace(" ", "-")]
            success_code, msg = ec_describe_tags(ec2_instance_payload)
            speech = msg

        except Exception as e:
            speech = ("I am sorry, something went wrong...")
            logger.info("Intent: {}: message: {}".format(
                handler_input.request_envelope.request.intent.name, str(e)))

        reprompt = "I am waiting for new instruction."
        handler_input.response_builder.speak(speech).ask(reprompt).set_card(
            SimpleCard("Cloud Control", speech)).set_should_end_session(
                False)

        return handler_input.response_builder.speak(speech).response

# Checks for instance classes
class InProgressEcInstanceCheckIntentHandler(AbstractRequestHandler):
    """Checks for instance in progress"""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (is_intent_name("EcInstanceCheckIntentHandler")(handler_input)
                and handler_input.request_envelope.request.dialog_state != DialogState.COMPLETED)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In InProgressEcInstanceCheckIntent")
        current_intent = handler_input.request_envelope.request.intent
        prompt = ""

        for slot_name, current_slot in six.iteritems(current_intent.slots):
            if slot_name in ["EcInstanceNameSelector",
                             "EcCheckTypeSelector"]:
                if (current_slot.confirmation_status != SlotConfirmationStatus.CONFIRMED
                        and current_slot.resolutions
                        and current_slot.resolutions.resolutions_per_authority[0]):
                    if current_slot.resolutions.resolutions_per_authority[0].status.code == StatusCode.ER_SUCCESS_MATCH:
                        if len(current_slot.resolutions.resolutions_per_authority[0].values) > 1:
                            prompt = "Select "

                            values = " or ".join([e.value.name for e in current_slot.resolutions.resolutions_per_authority[0].values])
                            prompt += values + " ?"
                            return handler_input.response_builder.speak(
                                prompt).ask(prompt).add_directive(
                                    ElicitSlotDirective(slot_to_elicit=current_slot.name)
                                    ).response
                    elif current_slot.resolutions.resolutions_per_authority[0].status.code == StatusCode.ER_SUCCESS_NO_MATCH:
                        if current_slot.name in required_slots:
                            prompt = "What {} are you looking for?".format(current_slot.name)

                            return handler_input.response_builder.speak(
                                prompt).ask(prompt).add_directive(
                                    ElicitSlotDirective(
                                        slot_to_elicit=current_slot.name
                                    )).response

        return handler_input.response_builder.add_directive(
            DelegateDirective(
                updated_intent=current_intent
            )).response

class CompletedEcInstanceCheckIntentHandler(AbstractRequestHandler):
    """Checks for instance completed"""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (is_intent_name("EcInstanceCheckIntent")(handler_input)
                and handler_input.request_envelope.request.dialog_state == DialogState.COMPLETED)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In CompletedEcInstanceCheckIntent")
        filled_slots = handler_input.request_envelope.request.intent.slots
        slot_values = get_slot_values(filled_slots)

        try:
            # create list of values
            ec2_instance_payload = [
                slot_values["EcInstanceNameSelector"]["resolved"].replace(" ", "-"),
                slot_values["EcCheckTypeSelector"]["resolved"]]
            success_code, msg = ec_check_instance(ec2_instance_payload)
            speech = msg

        except Exception as e:
            speech = ("I am sorry, something went wrong...")
            logger.info("Intent: {}: message: {}".format(
                handler_input.request_envelope.request.intent.name, str(e)))

        reprompt = "I am waiting for new instruction."
        handler_input.response_builder.speak(speech).ask(reprompt).set_card(
            SimpleCard("Cloud Control", speech)).set_should_end_session(
                False)

        return handler_input.response_builder.speak(speech).response

# Change some instance parameters classes
class InProgressEcChangeIntentHandler(AbstractRequestHandler):
    """Change instance parameters in progress"""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (is_intent_name("EcChangeIntentHandler")(handler_input)
                and handler_input.request_envelope.request.dialog_state != DialogState.COMPLETED)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In InProgressEcChangeIntent")
        current_intent = handler_input.request_envelope.request.intent
        prompt = ""

        for slot_name, current_slot in six.iteritems(current_intent.slots):
            if slot_name in ["EcInstanceNameSelector",
                             "EcChangeActionSelector"]:
                if (current_slot.confirmation_status != SlotConfirmationStatus.CONFIRMED
                        and current_slot.resolutions
                        and current_slot.resolutions.resolutions_per_authority[0]):
                    if current_slot.resolutions.resolutions_per_authority[0].status.code == StatusCode.ER_SUCCESS_MATCH:
                        if len(current_slot.resolutions.resolutions_per_authority[0].values) > 1:
                            prompt = "Select "

                            values = " or ".join([e.value.name for e in current_slot.resolutions.resolutions_per_authority[0].values])
                            prompt += values + " ?"
                            return handler_input.response_builder.speak(
                                prompt).ask(prompt).add_directive(
                                    ElicitSlotDirective(slot_to_elicit=current_slot.name)
                                    ).response
                    elif current_slot.resolutions.resolutions_per_authority[0].status.code == StatusCode.ER_SUCCESS_NO_MATCH:
                        if current_slot.name in required_slots:
                            prompt = "What {} are you looking for?".format(current_slot.name)

                            return handler_input.response_builder.speak(
                                prompt).ask(prompt).add_directive(
                                    ElicitSlotDirective(
                                        slot_to_elicit=current_slot.name
                                    )).response

        return handler_input.response_builder.add_directive(
            DelegateDirective(
                updated_intent=current_intent
            )).response

class CompletedEcChangeIntentHandler(AbstractRequestHandler):
    """Change instance parameters completed"""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (is_intent_name("EcChangeIntent")(handler_input)
                and handler_input.request_envelope.request.dialog_state == DialogState.COMPLETED)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In CompletedEcChangeIntent")
        filled_slots = handler_input.request_envelope.request.intent.slots
        slot_values = get_slot_values(filled_slots)

        try:
            # create list of values
            ec2_instance_payload = [
                slot_values["EcInstanceNameSelector"]["resolved"].replace(" ", "-"),
                slot_values["EcChangeActionSelector"]["resolved"],
                slot_values["EcChangeAttributeSelector"]["resolved"].replace(" ", ".")]
            success_code, msg = ec_change_instance(ec2_instance_payload)
            speech = msg

        except Exception as e:
            speech = ("I am sorry, cannot change this...")
            logger.info("Intent: {}: message: {}".format(
                handler_input.request_envelope.request.intent.name, str(e)))

        return handler_input.response_builder.speak(speech).response

sb.add_request_handler(LaunchRequestHandler())
sb.add_request_handler(InProgressEcCreateIntentHandler())
sb.add_request_handler(CompletedEcCreateIntentHandler())
sb.add_request_handler(InProgressEcTerminateIntentHandler())
sb.add_request_handler(CompletedEcTerminateIntentHandler())
sb.add_request_handler(InProgressEcActionStateIntentHandler())
sb.add_request_handler(CompletedEcActionStateIntentHandler())
sb.add_request_handler(InProgressEcTagIntentHandler())
sb.add_request_handler(CompletedEcTagIntentHandler())
sb.add_request_handler(InProgressEcDescribeTagsIntentHandler())
sb.add_request_handler(CompletedEcDescribeTagsIntentHandler())
sb.add_request_handler(InProgressEcInstanceCheckIntentHandler())
sb.add_request_handler(CompletedEcInstanceCheckIntentHandler())
sb.add_request_handler(InProgressEcChangeIntentHandler())
sb.add_request_handler(CompletedEcChangeIntentHandler())
sb.add_request_handler(HelpIntentHandler())
sb.add_request_handler(CancelOrStopIntentHandler())
sb.add_request_handler(FallbackIntentHandler())
sb.add_request_handler(SessionEndedRequestHandler())

sb.add_exception_handler(CatchAllExceptionHandler())

handler = sb.lambda_handler()
