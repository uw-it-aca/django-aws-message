import json
from logging import getLogger
import traceback
from django.conf import settings
from aws_message.aws import SNSException, extract_inner_message,\
    validate_message_body, subscribe
from aws_message.processor import ProcessorException
from aws_message.sqs import SQSQueue


logger = getLogger(__name__)


class GatherException(Exception):
    pass


class Gather(object):
    """
    Class to gather event messages from AWS SQS queue,
    validate and process their content
    """

    def __init__(self,
                 sqs_settings=None,
                 processor=None,
                 exception=None):
        """
        :param processor: A sub-class object of InnerMessageProcessor
        """

        if not processor:
            raise GatherException('missing event processor')

        self._processor = processor
        self._settings = sqs_settings if sqs_settings \
            else self._processor.get_queue_setting()

        self._topicArn = self._settings.get('TOPIC_ARN')

        self._queue = SQSQueue(settings=self._settings)
        # if Exception, abort!

    def gather_events(self):
        to_fetch = self._settings.get('MESSAGE_GATHER_SIZE')

        while to_fetch > 0:
            messages = self._queue.get_messages(to_fetch)

            if len(messages) == 0:
                logger.info("SQS queue %s is drained" % self._queue.url)
                break

            for msg in messages:
                try:
                    mbody = json.loads(msg.body)

                    if mbody['TopicArn'] != self._topicArn:
                        logger.warning('Unrecognized TopicARN: %s',
                                       mbody['TopicArn'])

                    if self._settings.get('VALIDATE_SNS_SIGNATURE', True):
                        validate_message_body(mbody)

                    if mbody['Type'] == 'Notification':
                        self._processor.process(extract_inner_message(mbody))

                    elif mbody['Type'] == 'SubscriptionConfirmation':
                        logger.info('SubscribeURL: %s', mbody['SubscribeURL'])

                except SNSException, ProcessorException as err:
                    # log message specific error, abort if unknown error
                    logger.error("ERROR: %s SKIP MESSAGE: %s" % (err, msg),
                                 traceback.format_exc().splitlines())
                else:
                    msg.delete()
                    # inform the queue that this message has been processed
