// Copyright 2018 Blade M. Doyle
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

//! Mining Stratum Worker
//!
//! A single mining worker (the pool manages a vec of Workers)
//!

use bufstream::BufStream;
use serde_json;
use serde_json::Value;
use std::net::TcpStream;
use reqwest;
use std::collections::HashMap;
use redis::{Client, Commands, Connection, RedisResult};
use std::iter;
use rand::{Rng, thread_rng};
use rand::distributions::Alphanumeric;
use queues::*;

use pool::logger::LOGGER;
use pool::proto::{RpcRequest, RpcError};
use pool::proto::{JobTemplate, LoginParams, StratumProtocol, SubmitParams, WorkerStatus};

// ----------------------------------------
// Worker Object - a connected stratum client - a miner
//

//#derive(Serialize, Deserialize, Debug)]
//pub struct AuthForm {
//    pub username: String,
//    pub password: String,
//}

#[derive(Debug)]
pub struct WorkerConfig {}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct Shares {
    pub edge_bits: u32,
    pub accepted: u64,
    pub rejected: u64,
    pub stale: u64,
}

impl Shares {
    pub fn new(edge_bits: u32) -> Shares {
        Shares {
            edge_bits: edge_bits,
            accepted: 0,
            rejected: 0,
            stale: 0,
        }
    }
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct WorkerShares {
    pub id: String,
    pub height: u64,
    pub difficulty: u64,
    pub shares: HashMap<u32, Shares>,
}

impl WorkerShares {
    pub fn new(id: String) -> WorkerShares {
        WorkerShares {
            id: id,
            height: 0,
            difficulty: 0,
            shares: HashMap::new(),
        }
    }
}


pub struct Worker {
    pub id: usize,
    pub rig_id: String,
    login: Option<LoginParams>,
    stream: BufStream<TcpStream>,
    protocol: StratumProtocol,
    error: bool,
    pub authenticated: bool,
    pub status: WorkerStatus,        // Runing totals - reported with stratum status message
    pub worker_shares: WorkerShares, // Share Counts for current block
    shares: Vec<SubmitParams>,
    request_ids: Queue<String>,     // Queue of request message ID's
    pub needs_job: bool,
    pub requested_job: bool,
    redis: Option<redis::Connection>,
    pub buffer: String,
}

impl Worker {
    /// Creates a new Stratum Worker.
    pub fn new(id: usize, stream: BufStream<TcpStream>) -> Worker {
        let mut rng = thread_rng();
        let rig_id: String = iter::repeat(())
            .map(|()| rng.sample(Alphanumeric))
            .take(16)
            .collect();
        Worker {
            id: id,
            rig_id: rig_id,
            login: None,
            stream: stream,
            protocol: StratumProtocol::new(),
            error: false,
            authenticated: false,
            status: WorkerStatus::new(id.to_string()),
            worker_shares: WorkerShares::new(id.to_string()),
            shares: Vec::new(),
            request_ids: queue![],
            needs_job: false,
            requested_job: false,
            redis: None,
            buffer: String::with_capacity(4096),
        }
    }

    /// Is the worker in error state?
    pub fn error(&self) -> bool {
        return self.error;
    }

    /// get the id
    pub fn id(&self) -> usize {
        return self.id;
    }

    /// get the rig_id
    pub fn rig_id(&self) -> String {
        return self.rig_id.clone();
    }

    /// get the full_id
    pub fn full_id(&self) -> String {
        let full_id: String = format!("{}-{}", self.id, self.rig_id.clone());
        return full_id;
    }

    /// Get worker login
    pub fn login(&self) -> String {
        match self.login {
            None => "None".to_string(),
            Some(ref login) => {
                let mut loginstr = login.login.clone();
                return loginstr.to_string();
            }
        }
    }

    /// Set job difficulty
    pub fn set_difficulty(&mut self, new_difficulty: u64) {
        self.status.difficulty = new_difficulty;
    }

    /// Set job height
    pub fn set_height(&mut self, new_height: u64) {
        self.status.height = new_height;
    }

    /// Reset worker_shares for a new block
    pub fn reset_worker_shares(&mut self, height: u64, difficulty: u64) {
        self.worker_shares.id = self.full_id();
        self.worker_shares.height = height;
        self.worker_shares.difficulty = difficulty;
        self.worker_shares.shares = HashMap::new();
    }
    
    /// Add a share to the worker_shares
    pub fn add_shares(&mut self, size: u32, accepted: u64, rejected: u64, stale: u64) {
        if self.worker_shares.shares.contains_key(&size) {
            match self.worker_shares.shares.get_mut(&size) {
                Some(mut shares) => {
                    shares.accepted += accepted;
                    shares.rejected += rejected;
                    shares.stale += stale;
                },
                None => {
                    // This cant happen
                }
            }
        } else {
            let mut shares: Shares = Shares::new(size);
            shares.accepted = accepted;
            shares.rejected = rejected;
            shares.stale = stale;
            self.worker_shares.shares.insert(size, shares);
        }
    }
    
    /// Send a response
    pub fn send_response(&mut self,
                         method: String,
                         result: Value,
                 ) -> Result<(), String> {
        // Get the request_id for this response
        // XXX TODO: Better matching of method?
        let req_id = self.request_ids.remove().unwrap(); // XXX TODO: verify unwrap
        trace!(
            LOGGER,
            "XXX SENDING RESPONSE: method: {}, result: {}, id: {}",
            method.clone(),
            result.clone(),
            req_id.clone(),
        );
        return self.protocol.send_response(
                &mut self.stream,
                method,
                result,
                Some(req_id),
            );
    }


    // This handles both a get_job_template response, and a job request
    /// Send a job to the worker
    pub fn send_job(&mut self, job: &mut JobTemplate) -> Result<(), String> {
        trace!(LOGGER, "Worker {} - Sending a job downstream: requested = {}", self.full_id(), self.requested_job);
        // Set the difficulty
        job.difficulty = self.status.difficulty;
        let requested = self.requested_job;
        self.needs_job = false;
        self.requested_job = false;
        let job_value = serde_json::to_value(job.clone()).unwrap();
        let full_id = self.full_id();
        let result;
        if requested {
            result = self.send_response(
                "getjobtemplate".to_string(),
                job_value,
            );
        } else {
            result = self.protocol.send_request(
                &mut self.stream,
                "job".to_string(),
                Some(job_value.clone()),
                Some("Stratum".to_string()),    // XXX UGLY
            );
        }
        match result {
            Ok(r) => { return Ok(r); }
            Err(e) => {
                self.error = true;
                error!(LOGGER, "{} - Failed to send job: {}", self.id, e);
                return Err(format!("{}", e));
            }
        }
    }

    /// Send worker mining status
    pub fn send_status(&mut self, status: WorkerStatus) -> Result<(), String> {
        trace!(LOGGER, "Worker {} - Sending worker status", self.id);
        let status_value = serde_json::to_value(status).unwrap();
        return self.send_response(
            "status".to_string(),
            status_value,
        );
    }

    /// Send OK Response
    pub fn send_ok(&mut self, method: String) -> Result<(), String> {
        trace!(LOGGER, "Worker {} - sending OK Response", self.id);
        return self.send_response(
            method.to_string(),
            serde_json::to_value("ok".to_string()).unwrap(),
        );
    }

    /// Send Err Response
    pub fn send_err(&mut self, method: String, message: String, code: i32) -> Result<(), String> {
        trace!(LOGGER, "Worker {} - sending Err Response", self.id);
        let e = RpcError {
            code: code,
            message: message.to_string(),
        };
        return self.protocol.send_error_response(
            &mut self.stream,
            method.to_string(),
            e,
        );
    }

    /// Return any pending shares from this worker
    pub fn get_shares(&mut self) -> Result<Option<Vec<SubmitParams>>, String> {
        if self.shares.len() > 0 {
            trace!(
                LOGGER,
                "Worker {} - Getting {} shares",
                self.id,
                self.shares.len()
            );
            let current_shares = self.shares.clone();
            self.shares = Vec::new();
            return Ok(Some(current_shares));
        }
        return Ok(None);
    }

    /// Worker Login
    pub fn do_login(&mut self, login_params: LoginParams) -> Result<(), String> {
        // Get the user id
        self.login = Some(login_params.clone());
        // Try to get this user id from the redis cache
        // Connect
        match self.redis {
            None => {
                match redis::Client::open("redis://redis-master/") {
                    Err(e) => {},
                    Ok(client) => {
                        // create connection from client and assing to
                        // self.redis if success
                        match client.get_connection() {
                            Err(e) => {},
                            Ok(con) => {
                                self.redis = Some(con);
                            },
                        }
                    },
                };
            },
            Some(_) => {},
        };
        let mut username = login_params.login.clone();

        let mut userid_key = format!("userid.{}", username);
        match self.redis {
            Some(ref mut redis) => {
                let response: usize = match redis.get(userid_key.clone()) {
                    Ok(id) => id,
                    Err(e) => 0,
                };
                if response != 0 {
                    self.id = response as usize;
                    debug!(LOGGER, "Got user login from redis: {}", self.id.clone());
                };
            },
            None => {}
        }
        if self.id != 0 {
            trace!(LOGGER, "User login found in cache: {}", self.id.clone());
            // We accepted the login
            return Ok(());
        }
        // XXX UGLY - nbminer sometimes appends ".default" to the end of a username
        if login_params.login.contains(".default") {
            username = username.replace(".default", "");
            userid_key = format!("userid.{}", username);
            match self.redis {
                Some(ref mut redis) => {
                    let response: usize = match redis.get(userid_key.clone()) {
                        Ok(id) => id,
                        Err(e) => 0,
                    };
                    if response != 0 {
                        self.id = response as usize;
                        error!(LOGGER, "Got user login from redis: {}", self.id.clone());
                    };
                },
                None => {}
            }
        }
        if self.id != 0 {
            trace!(LOGGER, "User login found in cache: {}", self.id.clone());
            // We accepted the login
            return Ok(());
        }
        // Didnt find user in the redis, try the database
        debug!(LOGGER, "Calling pool api to get userid");
        // Call the pool API server to Try to get the users ID based on login
        let client = reqwest::Client::new(); // api request client
        let mut response = client
            .get(format!("http://poolapi:13423/pool/userid/{}", username.clone()).as_str())
            .send(); // This could be Err
        let mut result = match response {
            Ok(r) => r,
            Err(e) => {
                self.error = true;
                debug!(LOGGER, "Worker {} - Failed to contact API server", self.id);
                return self.send_err(
                    "login".to_string(),
                    "Failed to contatct API server for user lookup".to_string(),
                    -32500,
                );
            }
        };
        if result.status().is_success() {
            let userid_json: Value = result.json().unwrap();
            trace!(LOGGER, "Got ID from database: {}", userid_json.clone());
            self.id = userid_json["id"].as_u64().unwrap() as usize;
            // We still need to validate the password if one is provided
            debug!(LOGGER, "Password length: {}", login_params.pass.chars().count());
            if login_params.pass.chars().count() > 0 {
                let mut response = client
                    .get("http://poolapi:13423/pool/users/id")
                    .basic_auth(username.clone(), Some(login_params.pass.clone()))
                    .send(); // This could be Err
                let mut result = match response {
                    Ok(r) => r,
                    Err(e) => {
                        self.error = true;
                        debug!(LOGGER, "Worker {} - Failed to contact API server", self.id);
                        return self.send_err(
                            "login".to_string(),
                            "Failed to contatct API server for user lookup".to_string(),
                            -32500,
                        );
                        //return Err("Login Failed to contatct API server for user lookup".to_string());
                    }
                };
                if ! result.status().is_success() {
                    self.error = true;
                    debug!(LOGGER, "Worker {} - Failed to log in", self.id);
                    return self.send_err(
                        "login".to_string(),
                        "Failed to log in".to_string(),
                        -32500,
                    );
                }
            }
            // Cache the user id in redis
            trace!(LOGGER, "Attempting to cache userid A: {} {}", userid_key.clone(), self.id.clone());
            match self.redis {
                Some(ref mut redis) => {
                    let _ : () = redis.set(userid_key.clone(), self.id.clone()).unwrap();
                },
                None => {
                    error!(LOGGER, "Worker {} - No redis connection, cant cache id", self.id);
                },
            }
        } else {
            //
            // No account exists.
            trace!(LOGGER, "Could not find user in the database: {}", result.status());
            // If we have been given a password, create an account now
            if ! login_params.pass.is_empty() {
                let mut auth_data = HashMap::new();
                auth_data.insert("username", username.clone());
                auth_data.insert("password", login_params.pass.clone());
                let mut response = client
                    .post("http://poolapi:13423/pool/users")
                    .form(&auth_data)
                    .send(); // This could be Err
                let mut result = match response {
                    Ok(r) => r,
                    Err(e) => {
                        self.error = true;
                        error!(LOGGER, "Worker {} - Failed contatct API server for user lookup", self.id);
                        return self.send_err(
                            "login".to_string(),
                            "Failed contatct API server for user lookup".to_string(),
                            -32500,
                        );
                    }
                };
                if result.status().is_success() {
                    // The response contains the id
                    let worker_json: Value = result.json().unwrap();
                    debug!(LOGGER, "Created ID in database: {}", worker_json);
                    self.id = worker_json["id"].as_u64().unwrap() as usize
                } else {
                    error!(LOGGER, "Failed to create user: {}", result.status());
                    self.error = true;
                    return self.send_err(
                        "login".to_string(),
                        "Failed to create user or Login".to_string(),
                        -32500,
                    );
                }
                return Ok(());
            } else {
                // We could not find the user in the database, and we dont
                // have a password to create the user, so we cant continue
                self.error = true;
                debug!(LOGGER, "Worker {} - Failed find user account", self.id);
                return self.send_err(
                    "login".to_string(),
                    "Login Failed to get your ID, please visit https://MWGrinPool.com and create an account".to_string(),
                    -32500,
                );
            }
        }
        return Ok(());
    }

    /// Worker Stats - NOT USED CURRENTLY
    pub fn get_worker_stats(&mut self, login_params: LoginParams) -> Result<(), String> {
        //
        // Get the workers stats
        // XXX DO WE NEED NBMINER workaround still ????
        let client = reqwest::Client::new();
        let mut response = client
            .get(format!("http://poolapi:13423/worker/stats/{}/0,1", self.id).as_str())
            .basic_auth(login_params.login.clone(), Some(login_params.pass.clone()))
            .send(); // This could be Err
        match response {
            Err(e) => {
                debug!(LOGGER, "Worker {} - Unable to fetch worker stats data", self.id);
                // Failed to get stats, but this is not fatal
            },
            Ok(mut result) => {
                if result.status().is_success() {
                    // Fill in worker stats with this data
                    // XXX TODO
                    let stats_json: Value = result.json().unwrap();
                    debug!(LOGGER, "Worker stats: {:?}", stats_json);
                    //self.status.accepted =  stats_json["total_shares_processed"].as_u64().unwrap();
                } else {
                    warn!(LOGGER, "Failed to get user stats: {}", result.status());
                }
            }
        }
        return Ok(());
    }


    /// Get and process messages from the connected worker
    // Method to handle requests from the downstream worker
    pub fn process_messages(&mut self) -> Result<(), String> {
        // XXX TODO: With some reasonable rate limiting (like N message per pass)
        // Read some messages from the upstream
        // Handle each request
        match self.protocol.get_message(&mut self.stream, &mut self.buffer) {
            Ok(rpc_msg) => {
                match rpc_msg {
                    Some(message) => {
                        trace!(LOGGER, "Worker {} - Got Message: {:?}", self.id, message);
                        // let v: Value = serde_json::from_str(&message).unwrap();
                        let req: RpcRequest = match serde_json::from_str(&message) {
                            Ok(r) => r,
                            Err(e) => {
                                // Do we want to diconnect the user for invalid RPC message ???
                                self.error = true;
                                debug!(LOGGER, "Worker {} - Got Invalid Message", self.id);
                                // XXX TODO: Invalid request
                                return Err(e.to_string());
                            }
                        };
                        trace!(
                            LOGGER,
                            "Worker {} - Received request type: {}",
                            self.id,
                            req.method
                        );
                        // Add this request id to the queue
                        self.request_ids.add(req.id.clone());
                        match req.method.as_str() {
                            "login" => {
                                debug!(LOGGER, "Worker {} - Accepting Login request", self.id);
                                if self.id != 0 {
                                    // dont log in again, just say ok
                                    debug!(LOGGER, "User already logged in: {}", self.id.clone());
                                    self.send_ok(req.method);
                                    return Ok(());
                                }
                                let params: Value = match req.params {
                                    Some(p) => p,
                                    None => {
                                        self.error = true;
                                        debug!(LOGGER, "Worker {} - Missing Login request parameters", self.id);
                                        return self.send_err(
                                            "login".to_string(),
                                            "Missing Login request parameters".to_string(),
                                            -32500,
                                        );
                                        // XXX TODO: Invalid request
                                        //return Err("Invalid Login request".to_string());
                                    }
                                };
                                let login_params: LoginParams = match serde_json::from_value(params)
                                {
                                    Ok(p) => p,
                                    Err(e) => {
                                        self.error = true;
                                        debug!(LOGGER, "Worker {} - Invalid Login request parameters", self.id);
                                        return self.send_err(
                                            "login".to_string(),
                                            "Invalid Login request parameters".to_string(),
                                            -32500,
                                        );
                                        // XXX TODO: Invalid request
                                        //return Err(e.to_string());
                                    }
                                };
                                // Call do_login()
                                match self.do_login(login_params) {
                                    Ok(_) => {
                                        // We accepted the login, send ok result
					                    self.authenticated = true;
                                        self.needs_job = false; // not until requested
                                        self.send_ok(req.method);
                                    },
                                    Err(e) => {
                                        return Err(e);
                                    }
                                }
                            }
                            "getjobtemplate" => {
                                trace!(LOGGER, "Worker {} - Accepting request for job", self.full_id());
                                self.needs_job = true;
                                self.requested_job = true;
                            }
                            "submit" => {
                                trace!(LOGGER, "Worker {} - Accepting share", self.id);
                                match serde_json::from_value(req.params.unwrap()) {
                                    Result::Ok(share) => {
                           			    self.shares.push(share);
                                    },
                                    Result::Err(err) => { }
                                };
                            }
                            "status" => {
                                trace!(LOGGER, "Worker {} - Accepting status request", self.id);
                                let status = self.status.clone();
                                self.send_status(status);
                            }
                            "keepalive" => {
                                trace!(LOGGER, "Worker {} - Accepting keepalive request", self.id);
                                self.send_ok(req.method);
                            }
                            _ => {
                                warn!(
                                    LOGGER,
                                    "Worker {} - Unknown request: {}",
                                    self.id,
                                    req.method.as_str()
                                );
                                self.error = true;
                                return Err("Unknown request".to_string());
                            }
                        };
                    }
                    None => {} // Not an error, just no messages for us right now
                }
            }
            Err(e) => {
                error!(
                    LOGGER,
                    "Worker {} - Error reading message: {}",
                    self.id,
                    e.to_string()
                );
                self.error = true;
                return Err(e.to_string());
            }
        }
        return Ok(());
    }
}
