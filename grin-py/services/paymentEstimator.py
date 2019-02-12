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

# Add a pool stats record ~per block


import sys
import requests
import json
import atexit
from time import sleep
import traceback


from grinbase.dbaccess import database

from grinlib import lib
from grinlib import pool

from grinbase.model.pool_blocks import Pool_blocks
from grinbase.model.worker_shares import Worker_shares

PROCESS = "paymentEstimator"
LOGGER = None
CONFIG = None

check_interval = 10

def main():
    CONFIG = lib.get_config()
    LOGGER = lib.get_logger(PROCESS)
    LOGGER.warn("=== Starting {}".format(PROCESS))
    # Connect to DB
    database = lib.get_db()
    esitmated = []  # Blocks we know have already been estimated - XXX TODO: Clean paid blocks out of this list

    while True:
        # Generate pool block reward estimates for all new and unlocked blocks
        try:
            database.db.initializeSession()
            unlocked_blocks = Pool_blocks.get_all_unlocked()
            new_blocks = Pool_blocks.get_all_new()
            unlocked_blocks_h = [blk.height for blk in unlocked_blocks]
            new_blocks_h = [blk.height for blk in new_blocks]

            need_estimates = []
            for height in unlocked_blocks_h + new_blocks_h:
                if height not in esitmated:
                    need_estimates.append(height)
            if need_estimates:
                LOGGER.warn("Will ensure estimate for blocks: {}".format(need_estimates))
    
                # Generate Estimate
                for height in need_estimates:
                    LOGGER.warn("Ensure estimate for block: {}".format(height))
                    payout_map = pool.calculate_block_payout_map(height, 60, LOGGER, True)
                    esitmated.append(height)
                    LOGGER.warn("Completed estimate for block: {}".format(height))
    
                LOGGER.warn("Completed estimates")
            database.db.destroySession()
            sleep(check_interval)
        except Exception as e:  # AssertionError as e:
            LOGGER.error("Something went wrong: {} - {}".format(e, traceback.print_stack()))
    
        LOGGER.warn("=== Completed {}".format(PROCESS))
        sleep(check_interval)

if __name__ == "__main__":
    main()
