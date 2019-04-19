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
import redis
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

# Name of this service
PROCESS = "shareAggr"

# Debung messages get printed?
debug = True

# Which RMQ servers to conect to. local cluster "rmq" by default
RMQ = "rmq"

# globals used by per-block per user aggrreagated rig shares records (stored in mysql)
SHARE_EXPIRETIME = 59
POOLBLOCK_MUTEX = threading.Lock()
SHARES_MUTEX = threading.Lock()
SHARES = {}

RMQ_ACK = {}

# globals used by individual rig-data records (stored in redis)
REDIS_RIGDATA_KEY = "rigdata"
REDIS_RIGDATA_EXPIRETIME = 60 * 60 * 24 + 60
RIGDATA_GROUPSIZE = 5.0
RIGDATA_MUTEX = threading.Lock()
RIGDATA = {}

# Example share message:  {29: Shares { edge_bits: 29, accepted: 7, rejected: 0, stale: 0 }}
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
        new_pool_block = Pool_blocks(
                hash=hash, 
                height=height, 
                nonce=nonce, 
                actual_difficulty=actual_difficulty, 
                net_difficulty=net_difficulty, 
                timestamp=timestamp, 
                found_by=found_by, 
                state=state
            )
        duplicate = lib.get_db().db.createDataObj_ignore_duplicates(new_pool_block)
        if duplicate:
            logger.warn("Failed to add duplicate Pool Block: {}".format(height))
        else:
            logger.warn("Added Pool Block: {}".format(height))
    finally:
        POOLBLOCK_MUTEX.release()


# Accept a workers share record, add it to all the data structures we want
def addWorkerShares(logger, channel, delivery_tag, timestamp, height, worker, workerid, rig_id, agent, difficulty, shares_data):
    global SHARES_MUTEX
    global SHARE_RE
    global SHARES
    global RIGDATA_MUTEX
    global RIGDATA
    global RIGDATA_GROUPSIZE
    logger.warn("New Worker Shares: Height: {}, Worker: {}, RigID: {}, Agent: {}, Difficulty: {}, SharesData: {}".format(height, worker, rig_id, agent, difficulty, shares_data))
    # Parse the sharedata
    # TEST: shares_data = "{29: Shares { edge_bits: 29, accepted: 7, rejected: 0, stale: 0 }, 31: Shares { edge_bits: 31, accepted: 4, rejected: 0, stale: 0 }}"
    all_shares = SHARE_RE.findall(shares_data)
    #logger.warn("addWorkerShares processing all_shares: {}".format(all_shares))

    for shares in all_shares:
        debug and logger.warn("shares: {}".format(shares))
        edge_bits, accepted, rejected, stale = shares
        edge_bits = int(edge_bits)
        # Adjust for minimum share difficulty
        accepted = int(accepted) * difficulty
        rejected = int(rejected) * difficulty
        stale    = int(stale)    * difficulty
        logger.warn("New Worker Shares: Difficulty: {}, Accepted: {}, Rejected: {}, Stale: {}".format(difficulty, accepted, rejected, stale))

        ##
        # Add the data to Aggregated counts of all rigs for this worker
        SHARES_MUTEX.acquire()
        try:
            if height not in  SHARES:
                SHARES[height] = { "timestamp": timestamp, }
            if worker not in SHARES[height]:
                SHARES[height][worker] = {}
            if edge_bits not in SHARES[height][worker]:
                SHARES[height][worker][edge_bits] = { 'difficulty': difficulty, 'accepted': 0, 'rejected': 0, 'stale': 0 }
            SHARES[height][worker][edge_bits]['difficulty'] = difficulty
            SHARES[height][worker][edge_bits]['accepted'] += accepted
            SHARES[height][worker][edge_bits]['rejected'] += rejected
            SHARES[height][worker][edge_bits]['stale'] += stale
            logger.warn("XXXX  SHARES[{}][{}][{}] = {}".format(height, worker, edge_bits, SHARES[height][worker][edge_bits]))

            if height not in RMQ_ACK:
                RMQ_ACK[height] = {}
            if channel not in RMQ_ACK[height]:
                RMQ_ACK[height][channel] = []
            RMQ_ACK[height][channel].append(delivery_tag)
        finally:
            SHARES_MUTEX.release()

        ##
        # Add the individual rig data for each worker (goes into redis for per-rig data)
        RIGDATA_MUTEX.acquire()
        edge_bits_s = str(edge_bits)
        group_height = int((height - height % RIGDATA_GROUPSIZE) + RIGDATA_GROUPSIZE)
        try:
            if group_height not in RIGDATA:
                RIGDATA[group_height] = {}
            if worker not in RIGDATA[group_height]:
                RIGDATA[group_height][worker] = {}
            if rig_id not in RIGDATA[group_height][worker]:
                RIGDATA[group_height][worker][rig_id] = {}
            if workerid not in RIGDATA[group_height][worker][rig_id]:
                RIGDATA[group_height][worker][rig_id][workerid] = {}
            if edge_bits_s not in RIGDATA[group_height][worker][rig_id][workerid]:
                RIGDATA[group_height][worker][rig_id][workerid][edge_bits_s] = {'difficulty': 0, 'accepted': 0, 'rejected': 0, 'stale': 0 }
            RIGDATA[group_height][worker][rig_id][workerid][edge_bits_s]['difficulty'] = difficulty
            RIGDATA[group_height][worker][rig_id][workerid][edge_bits_s]['agent'] = agent
            RIGDATA[group_height][worker][rig_id][workerid][edge_bits_s]['accepted'] += accepted
            RIGDATA[group_height][worker][rig_id][workerid][edge_bits_s]['rejected'] += rejected
            RIGDATA[group_height][worker][rig_id][workerid][edge_bits_s]['stale'] += stale
            logger.warn("XXXX  RIGDATA[{}][{}][{}][{}][{}] = {}".format(group_height, worker, rig_id, workerid, edge_bits, RIGDATA[group_height][worker][rig_id][workerid][edge_bits_s]))
        finally:
            RIGDATA_MUTEX.release()


def share_handler(ch, method, properties, body):
    global LOGGER
    global SHARE_EXPIRETIME

    LOGGER.warn("= Starting ShareHandler")
    sys.stdout.flush()
    #print("{}".format(body.decode("utf-8") ))
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
        LOGGER.warn("Timestamp String: {}".format(content["log_timestamp"]))
        s_timestamp = dateutil.parser.parse(str(content["log_timestamp"]))
        s_height = int(content["height"])
        s_difficulty = int(content["difficulty"])
        s_worker = int(content["worker"])
        if s_worker == 0:
            s_worker = 1
        try:
            s_workerid = content["workerid"]
        except Exception as e:
            s_workerid = "default"
        try:
            s_rigid = content["rigid"]
        except Exception as e:
            s_rigid = "0"
        try:
            s_agent = content["agent"]
        except Exception as e:
            s_agent = "unknown"
        s_sharedata = content["sharedata"]
        addWorkerShares(LOGGER, ch, method.delivery_tag, s_timestamp, s_height, s_worker, s_workerid, s_rigid, s_agent, s_difficulty, s_sharedata)
    elif content["type"] == "poolblocks":
        s_timestamp = dateutil.parser.parse(str(content["log_timestamp"]))
        s_height = int(content["height"])
        s_hash = content["hash"]
        s_worker =  1 # grin log does not know, credit Pool Admin
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

def ShareCommitScheduler(max_lag, logger):
    global SHARES_MUTEX
    global SHARES
    while True:
        try:
            database = lib.get_db()
            chain_height = Blocks.get_latest().height
            share_height = Worker_shares.get_latest_height()
            logger.warn("SHARES commit scheduler - chain_height = {}, share_height = {}".format(chain_height, share_height))
            SHARES_MUTEX.acquire()
            try:
                while share_height < (chain_height - max_lag):
                    share_height += 1
                    if share_height not in SHARES.keys():
                        # Even if there are no shares in the pool at all for this block, we still need to create a filler record at this height
                        logger.warn("Processed 0 shares in block {} - Creating filler record".format(share_height))
                        filler_worker_shares_rec = Worker_shares(
                                height = share_height,
                                user_id = 1, # Pool User
                                timestamp = datetime.utcnow(),
                            )
                        database.db.createDataObj(filler_worker_shares_rec)
                    else:
                        # Commit SHARES
                        logger.warn("Commit SHARES for height: {}".format(share_height))
                        # Get and remove the timestamp
                        ts = SHARES[share_height].pop("timestamp", datetime.utcnow())
                        for worker, worker_shares in SHARES[share_height].items():
                            # Get existing share record for this user at this height
                            worker_shares_rec = Worker_shares.get_by_height_and_id(share_height, worker)
                            if worker_shares_rec is None:
                                # No existing record for this worker at this height, create it
                                logger.warn("This is a new share record for worker {} at height {}".format(worker, share_height))
                                worker_shares_rec = Worker_shares(
                                    height = share_height,
                                    user_id = worker,
                                    timestamp = ts,
                                )
                                database.db.createDataObj(worker_shares_rec)
                            else:
                                # Add to the existing record
                                logger.warn("Add to existing Worker Shares: Accepted: {}, Rejected: {}, Stale: {}".format(accepted, rejected, stale))
                            for edge_bits, shares_count in worker_shares.items():
                                logger.warn("YYY: Commit new worker shares: {}".format(shares_count))
                                worker_shares_rec.add_shares(
                                    edge_bits,
                                    shares_count["difficulty"],
                                    shares_count["accepted"],
                                    shares_count["rejected"],
                                    shares_count["stale"]
                                  )
                                logger.warn("Worker Shares: {}".format(worker_shares_rec))
                    # Ack the RMQ shares messages
#                    for channel, tags in RMQ_ACK[share_height].items():
                        # bulk-ack up to the latest message we processed
#                        channel.basic_ack(delivery_tag=max(tags), multiple=True)
                    # Discard the processed messages
                    SHARES.pop(share_height, None)
                    RMQ_ACK.pop(share_height, None)
            finally:
                database.db.getSession().commit()
                SHARES_MUTEX.release()
                lib.teardown_db()
            time.sleep(30)
        except Exception as e:
            lib.teardown_db()
            logger.error("Something went wrong: {}\n{}".format(e, traceback.format_exc().splitlines()))
            time.sleep(10)
            
def RigDataCommitScheduler(max_lag, logger):
    global RIGDATA_MUTEX
    global RIGDATA
    global REDIS_RIGDATA_KEY
    global REDIS_RIGDATA_EXPIRETIME
    while True:
        try:
            redisdb = lib.get_redis_db()
            while True:
                database = lib.get_db()
                chain_height = Blocks.get_latest().height
                logger.warn("RIGDATA commit scheduler - chain_height = {}".format(chain_height))
                RIGDATA_MUTEX.acquire()
                try:
                    for height in [h for h in RIGDATA.keys() if h < (chain_height - max_lag)]:
                        logger.warn("Commit RIGDATA for height: {}".format(height))
                        # Picke RIGDATA and write to redis
                        for user, rigdata in RIGDATA[height].items():
                            key = "{}.{}.{}".format(REDIS_RIGDATA_KEY, height, user) 
                            if redisdb.exists(key):
                                logger.warn("XXX TODO - MERGE THIS ADDITIONAL SHARE DATA")
                            else:   
                                redisdb.set(key, json.dumps(rigdata), ex=REDIS_RIGDATA_EXPIRETIME)
                        RIGDATA.pop(height, None)
                finally:
                    RIGDATA_MUTEX.release()
                    lib.teardown_db()
                time.sleep(30)
        except Exception as e:
            logger.error("Something went wrong: {}\n{}".format(e, traceback.format_exc().splitlines()))
            lib.teardown_db()
            time.sleep(10)
            
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
    # rmq_endpoints = json.loads(CONFIG[PROCESS]["rmq"])

    RABBITMQ_USER = os.environ["RABBITMQ_USER"]
    RABBITMQ_PASSWORD = os.environ["RABBITMQ_PASSWORD"]

    try:
       RMQ = os.environ["RMQ"]
    except KeyError as e:
       LOGGER.warn("Cant determine RMQ servsers, default to {}".format(RMQ))

    ##
    # Start a thread to commit share records
    max_lag = 3 # Allow shares to lag up to max_lag behind the blockchain before filler record is created
    commit_thread = threading.Thread(target = ShareCommitScheduler, args = (max_lag, LOGGER,))
    commit_thread.start()

    ## 
    max_lag = 3 # Allow rigdata to lag up to max_lag behind the blockchain
    rigdata_thread = threading.Thread(target = RigDataCommitScheduler, args = (max_lag, LOGGER,))
    rigdata_thread.start()

    ##
    # Start a pika consumer thread for each rabbit we want to consume from
    for rmq in RMQ.split():
        try:
            rmq_thread = threading.Thread(target = RmqConsumer, args = (rmq, ))
            rmq_thread.start()
        except Exception as e:
            logger.error("Failed to connect to RMQ: {} - {}".format(rmq, e))

if __name__ == "__main__":
    main()

