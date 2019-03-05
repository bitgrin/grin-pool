#!/usr/bin/python

# Copyright 2018 Blade M. Doyle
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Watches the pool logs and adds the records for pool shares:
#   pool log -> pool_shares: height, nonce, *user_address*, *expected_difficulty*

from datetime import datetime
import dateutil.parser
import time
import traceback
import json
import sys
import os
import atexit
import threading
import pika
import re

from grinlib import lib
from grinlib import grin

from grinbase.model.blocks import Blocks
from grinbase.model.worker_shares import Worker_shares
from grinbase.model.shares import Shares
from grinbase.model.pool_blocks import Pool_blocks
from grinbase.model.pool_stats import Pool_stats
from grinbase.model.worker_stats import Worker_stats # XXX TODO: mark worker_stats record dirty if that users worker_shares record is updated


# so hard...
import pprint
pp = pprint.PrettyPrinter(indent=4)

PROCESS = "shareAggr"

# globals used by shareHandler callback
SHARE_EXPIRETIME = None
POOLBLOCK_MUTEX = threading.Lock()
SHARE_MUTEX = threading.Lock()

# Ex:  {29: Shares { edge_bits: 29, accepted: 7, rejected: 0, stale: 0 }}
SHARE_RE = re.compile('{ edge_bits: (\d+), accepted: (\d+), rejected: (\d+), stale: (\d+) }')


# Add a Pool_block (for full solutions)
def addPoolBlock(logger, timestamp, height, hash, found_by, serverid):
    global POOLBLOCK_MUTEX
    POOLBLOCK_MUTEX.acquire()
    database = lib.get_db()
    try:
        logger.warn("Adding A PoolBlock: Timestamp: {}, ServerID: {}, Height: {}, Hash: {}".format(timestamp, serverid, height, hash))
        state = "new"
        this_block = Blocks.get_by_height(height)
        while this_block is None:
            this_block = Blocks.get_by_height(height) 
            time.sleep(1)
        nonce = this_block.nonce
        actual_difficulty = grin.difficulty(this_block.hash, this_block.edge_bits, this_block.secondary_scaling)
        net_difficulty = grin.get_network_difficulty(height)
        # Create the DB record
        new_pool_block = Pool_blocks(hash=hash, height=height, nonce=nonce, actual_difficulty=actual_difficulty, net_difficulty=net_difficulty, timestamp=timestamp, found_by=found_by, state=state)
        duplicate = lib.get_db().db.createDataObj_ignore_duplicates(new_pool_block)
        if duplicate:
            logger.warn("Failed to add duplicate Pool Block: {}".format(height))
        else:
            logger.warn("Added Pool Block: {}".format(height))
    finally:
        POOLBLOCK_MUTEX.release()


# Add a workers share record
def addWorkerShares(logger, height, worker, rig_id, difficulty, shares_data):
    global SHARE_MUTEX
    global SHARE_RE
    logger.warn("New Worker Shares: Height: {}, Worker: {}, RigID: {}, Difficulty: {}, SharesData: {}".format(height, worker, rig_id, difficulty, shares_data))
    # Parse the sharedata
    # TEST: shares_data = "{29: Shares { edge_bits: 29, accepted: 7, rejected: 0, stale: 0 }, 31: Shares { edge_bits: 31, accepted: 4, rejected: 0, stale: 0 }}"
    all_shares = SHARE_RE.findall(shares_data)
    logger.warn("all_shares: {}".format(all_shares))
    SHARE_MUTEX.acquire()
    database = lib.get_db()
    try:
        for shares in all_shares:
            logger.warn("shares: {}".format(shares))
            edge_bits, accepted, rejected, stale = shares
            edge_bits = int(edge_bits)
            # Adjust for minimum share difficulty
            accepted = int(accepted) * difficulty
            rejected = int(rejected) * difficulty
            stale    = int(stale)    * difficulty
            logger.warn("New Worker Shares: Accepted: {}, Rejected: {}, Stale: {}".format(accepted, rejected, stale))
            # Get existing share record for this user at this height
            worker_shares_rec = Worker_shares.get_by_height_and_id(height, worker)
            if worker_shares_rec is None:
                # No existing record, create it
                logger.warn("This is a new share record for worker: {}".format(worker))
                worker_shares_rec = Worker_shares(
                        height = height,
                        user_id = worker,
                        timestamp = datetime.utcnow(),
                    )
                database.db.createDataObj(worker_shares_rec)
                worker_shares_rec.add_shares(edge_bits, difficulty, accepted, rejected, stale)
                # database.db.getSession().commit()
            else:
                # Add to the existing record
                logger.warn("Adding to existing Worker Shares: Accepted: {}, Rejected: {}, Stale: {}".format(accepted, rejected, stale))
                worker_shares_rec.add_shares(edge_bits, difficulty, accepted, rejected, stale)
                logger.warn("Added Worker Shares: {}".format(worker_shares_rec))
    finally:
        database.db.getSession().commit()
        SHARE_MUTEX.release()
        lib.teardown_db()


def share_handler(ch, method, properties, body):
    global LOGGER
    global SHARE_EXPIRETIME

    LOGGER.warn("= Starting ShareHandler")
    sys.stdout.flush()
    print("{}".format(body.decode("utf-8") ))
    sys.stdout.flush()
    content = json.loads(body.decode("utf-8"))
    LOGGER.warn("PUT message: {}".format(content))
    LOGGER.warn("Current Share -  Height: {} - Type: {}".format(content["height"], content["type"]))

#    # Dont process very old messages
#    if (HEIGHT - int(content["height"])) > SHARE_EXPIRETIME:
#        ch.basic_ack(delivery_tag = method.delivery_tag)
#        LOGGER.error("Dropping expired {} - Height: {}".format(content["type"], content["height"]))
#        return

    # Process worker shares message
    if content["type"] == "share":
        s_timestamp = datetime.utcnow() # XXX TODO FIX THIS - dateutil.parser.parse(str(datetime.utcnow().year) + " " + content["log_timestamp"])
        s_height = int(content["height"])
        s_difficulty = int(content["difficulty"])
        s_worker = int(content["worker"])
        s_rigid = content["rigid"]
        s_sharedata = content["sharedata"]
        addWorkerShares(LOGGER, s_height, s_worker, s_rigid, s_difficulty, s_sharedata)
    elif content["type"] == "poolblocks":
        s_timestamp = datetime.utcnow() # XXX TODO FIX THIS - dateutil.parser.parse(str(datetime.utcnow().year) + " " + content["log_timestamp"])
        s_height = int(content["height"])
        s_hash = content["hash"]
        s_worker =  1 # XXX TODO  FIX THIS int(content["worker"])
        serverid = content["serverid"]
        addPoolBlock(LOGGER, s_timestamp, s_height, s_hash, s_worker, serverid)
    else:
        LOGGER.warn("Invalid message type: {}".format(content["type"]))
    sys.stdout.flush()

     
def RmqConsumer(host):
    global LOGGER
    global RABBITMQ_USER
    global RABBITMQ_PASSWORD
    while True:
        try:
            credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASSWORD)
            connection = pika.BlockingConnection(pika.ConnectionParameters(
                    host=host,
                    credentials=credentials))
            channel = connection.channel()
            channel.basic_qos(prefetch_size=0, prefetch_count=0, all_channels=True)
            channel.basic_consume(share_handler,
                                  queue='poolblocks',
                                  no_ack=True)
            channel.basic_consume(share_handler,
                                  queue='shares',
                                  no_ack=True)
            channel.start_consuming()
        except Exception as e:
            LOGGER.error("Something went wrong: {}\n{}".format(e, traceback.format_exc().splitlines()))
            sys.stdout.flush()
            time.sleep(1)

def ShareFillerScheduler(max_lag, logger):
    try:
        while True:
            database = lib.get_db()
            chain_height = Blocks.get_latest().height
            share_height = Worker_shares.get_latest_height()
            logger.warn("chain_height = {}, share_height = {}".format(chain_height, share_height))
            while share_height < (chain_height - max_lag):
                share_height += 1
                logger.warn("chain_height = {}, share_height = {}".format(chain_height, share_height))
                logger.warn("Processed 0 shares in block {} - Creating filler record".format(share_height))
                # Even if there are no shares in the pool at all for this block, we still need to create a filler record at this height
                filler_worker_shares_rec = Worker_shares(
                        height = share_height,
                        user_id = 1, # Pool User
                        timestamp = datetime.utcnow(),
                    )
                database.db.createDataObj(filler_worker_shares_rec)
                #share_height = Worker_shares.get_latest_height()
            lib.teardown_db()
            time.sleep(30)
    except Exception as e:
        logger.error("Something went wrong: {}\n{}".format(e, traceback.format_exc().splitlines()))
        time.sleep(1)
            
def main():
    global LOGGER
    global CONFIG
    global SHARE_EXPIRETIME
    global RABBITMQ_USER
    global RABBITMQ_PASSWORD
    CONFIG = lib.get_config()

    LOGGER = lib.get_logger(PROCESS)
    LOGGER.warn("=== Starting {}".format(PROCESS))

    SHARE_EXPIRETIME = int(CONFIG[PROCESS]["share_expire_time"])
    rmq_endpoints = json.loads(CONFIG[PROCESS]["rmq"])

    RABBITMQ_USER = os.environ["RABBITMQ_USER"]
    RABBITMQ_PASSWORD = os.environ["RABBITMQ_PASSWORD"]

    ##
    # Start a thread to commit filler records (in the case where nobody is mining and no shares are processed)
    max_lag = 5 # Allow shares to lag up to max_lag behind the blockchain
    commit_thread = threading.Thread(target = ShareFillerScheduler, args = (max_lag, LOGGER,))
    commit_thread.start()

    ##
    # Start a pika consumer thread for each rabbit we want to consume from
    for rmq in rmq_endpoints:
        rmq_thread = threading.Thread(target = RmqConsumer, args = (rmq, ))
        rmq_thread.start()

if __name__ == "__main__":
    main()

