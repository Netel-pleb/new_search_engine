# The MIT License (MIT)
# Copyright © 2023 Yuma Rao
# TODO(developer): Set your name
# Copyright © 2023 <your name>

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.


import time

# Bittensor
import bittensor as bt
from opensearchpy import OpenSearch

# Bittensor Validator Template:
import otika
from otika.protocol import SearchSynapse
from otika.utils.uids import get_random_uids

# import base validator class which takes care of most of the boilerplate
from otika.base.validator import BaseValidatorNeuron

import os
import random
import torch
from dotenv import load_dotenv
from datetime import datetime


def random_line(a_file="queries.txt"):
    if not os.path.exists(a_file):
        bt.logging.error(f"Keyword file not found at location: {a_file}")
        exit(1)
    lines = open(a_file).read().splitlines()
    return random.choice(lines)


def check_integrity(response):
    """
    This function checks the integrity of the response.
    """
    # TODO: response correctness checking logic
    return True


class Validator(BaseValidatorNeuron):
    """
    Your validator neuron class. You should use this class to define your validator's behavior. In particular, you should replace the forward function with your own logic.

    This class inherits from the BaseValidatorNeuron class, which in turn inherits from BaseNeuron. The BaseNeuron class takes care of routine tasks such as setting up wallet, subtensor, metagraph, logging directory, parsing config, etc. You can override any of the methods in BaseNeuron if you need to customize the behavior.

    This class provides reasonable default behavior for a validator such as keeping a moving average of the scores of the miners and using them to set weights at the end of each epoch. Additionally, the scores are reset for new hotkeys at the end of each epoch.
    """

    def __init__(self, config=None):
        super(Validator, self).__init__(config=config)

        bt.logging.info("load_state()")
        self.load_state()

        load_dotenv()

        # TODO: ElasticSearch?
        opensearch_endpoint = os.environ["OPENSEARCH_ENDPOINT"]
        username = os.environ["OPENSEARCH_USERNAME"]
        password = os.environ["OPENSEARCH_PASSWORD"]
        self.search_client = OpenSearch(
            [opensearch_endpoint],
            http_auth=(username, password),
            use_ssl=False,
            verify_certs=False,
        )

    def get_rewards(self, query, responses):
        scores = torch.zeros(len(responses))

        zero_score_mask = torch.ones(len(responses))

        rank_scores = torch.zeros(len(responses))

        avg_ages = torch.zeros(len(responses))
        avg_age_scores = torch.zeros(len(responses))
        now = datetime.now()
        max_avg_age = 0
        for i, response in enumerate(responses):
            if not check_integrity(response):
                zero_score_mask[i] = 0
                continue
            for doc in response:
                avg_ages[i] += (now - doc.created_at).total_seconds()
            avg_ages[i] /= len(response)
            max_avg_age = max(max_avg_age, avg_ages[i])
        avg_age_scores = 1 - (avg_ages / (max_avg_age + 1))
        scores = avg_age_scores * 0.5

        return torch.bitwise_and(scores, zero_score_mask)

    async def forward(self):
        """
        Validator forward pass. Consists of:
        - Generating the query
        - Querying the miners
        - Getting the responses
        - Rewarding the miners
        - Updating the scores
        """

        miner_uids = get_random_uids(self, k=self.config.neuron.sample_size)

        query_string = random_line()
        search_query = SearchSynapse(query_string=query_string, length=5)

        bt.logging.info(
            f"Sending search: {search_query} to miners: {[(uid, self.metagraph.axons[uid] )for uid in miner_uids]}"
        )

        # The dendrite client queries the network.
        responses = await self.dendrite(
            # Send the query to selected miner axons in the network.
            axons=[self.metagraph.axons[uid] for uid in miner_uids],
            synapse=search_query,
            deserialize=True,
            timeout=60,
        )

        # Log the results for monitoring purposes.
        bt.logging.info(f"Received responses: {responses}")

        rewards = self.get_rewards(query=search_query, responses=responses)

        bt.logging.info(f"Scored responses: {rewards}")
        # Update the scores based on the rewards. You may want to define your own update_scores function for custom behavior.
        self.update_scores(rewards, miner_uids)


# The main function parses the configuration and runs the validator.
if __name__ == "__main__":
    with Validator() as validator:
        while True:
            bt.logging.info("Validator running...", time.time())
            time.sleep(5)
