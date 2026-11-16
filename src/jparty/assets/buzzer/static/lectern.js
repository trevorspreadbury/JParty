// The lectern page is left open for hours, across many JParty restarts, so it
// never gives up and never reloads itself (a reload would leave full screen).
// It keeps retrying until the server is back, and the server then sends the
// seat's current state.
var updater = {
    socket: null,
    playerNumber: null,
    reconnectAttempts: 0,
    // First retry delay. Each failed try doubles it, up to maxReconnectDelay.
    reconnectDelay: 1000,
    maxReconnectDelay: 5000,
    lightsInterval: null,
    lightsRunning: false,
    currentLightStage: 0,
    reconnectTimer: null,
    replaced: false,
    // Close code the server sends when another lectern page takes this slot.
    // Matches LECTERN_REPLACED_CLOSE_CODE in handlers.py.
    replacedCloseCode: 4000,
    // The server sends a HEARTBEAT every 3 seconds (LECTERN_HEARTBEAT_SECONDS
    // in handlers.py). Hearing nothing for this long means the connection
    // died without closing, so the page drops it and reconnects.
    staleAfter: 10000,
    // A connection attempt that hasn't opened by now is dropped and retried.
    connectTimeout: 5000,
    // After losing the server, keep showing the player this long before
    // falling back to the logo. Short Wi-Fi blips don't blank the screen, but
    // closing JParty does.
    logoAfter: 5000,
    lastMessageAt: 0,
    socketStartedAt: 0,
    logoTimer: null,
    watchdogTimer: null,

    // True while a socket is connecting or open, or a reconnect is waiting.
    isConnectingOrConnected: function() {
        if (updater.reconnectTimer !== null) {
            return true;
        }
        return !!updater.socket && (
            updater.socket.readyState === WebSocket.CONNECTING ||
            updater.socket.readyState === WebSocket.OPEN
        );
    },

    start: function() {
        // Never open a second socket while one is live; the server would
        // close the first and the page would end up fighting itself.
        if (updater.socket && (
            updater.socket.readyState === WebSocket.CONNECTING ||
            updater.socket.readyState === WebSocket.OPEN
        )) {
            return;
        }
        this.playerNumber = typeof playerNumber !== 'undefined' ? playerNumber : 0;
        var url = "ws://" + location.host + "/lecternsocket?player=" + this.playerNumber;
        var socket = new WebSocket(url);
        updater.socket = socket;
        updater.socketStartedAt = Date.now();

        socket.onopen = function(event) {
            console.log("Lectern WebSocket connected for player " + updater.playerNumber);
            updater.reconnectAttempts = 0;
            updater.lastMessageAt = Date.now();
        };

        socket.onmessage = function(event) {
            if (updater.socket !== socket) {
                return;
            }
            updater.lastMessageAt = Date.now();
            var jsondata = JSON.parse(event.data);
            updater.handleMessage(jsondata);
        };

        socket.onerror = function(error) {
            console.error("WebSocket error:", error);
        };

        socket.onclose = function(event) {
            console.log("WebSocket closed");
            if (updater.socket !== socket) {
                return;
            }
            if (event.code === updater.replacedCloseCode) {
                updater.replaced = true;
                var nameElement = document.getElementById("player-name");
                nameElement.textContent = "Opened on another screen";
                nameElement.style.display = "";
                return;
            }
            updater.connectionLost();
        };
    },

    // Start the logo countdown and schedule the next connection attempt.
    connectionLost: function() {
        if (updater.logoTimer === null) {
            updater.logoTimer = setTimeout(function() {
                updater.logoTimer = null;
                updater.showNoPlayer();
            }, updater.logoAfter);
        }
        updater.handleReconnect();
    },

    // Stop the logo countdown once the server has sent this seat's state.
    connectionRestored: function() {
        if (updater.logoTimer !== null) {
            clearTimeout(updater.logoTimer);
            updater.logoTimer = null;
        }
    },

    // Abandon a socket that has gone quiet or never opened. Its handlers are
    // detached first, because closing a dead connection can take a long time
    // to report back.
    dropSocket: function() {
        var socket = updater.socket;
        if (!socket) {
            return;
        }
        console.log("Lectern connection went quiet, reconnecting");
        socket.onopen = null;
        socket.onmessage = null;
        socket.onclose = null;
        socket.onerror = null;
        updater.socket = null;
        try {
            socket.close();
        } catch (error) {
            console.error("Error closing stale socket:", error);
        }
        updater.connectionLost();
    },

    // Runs every second and drops a connection that has stopped working.
    checkConnection: function() {
        var socket = updater.socket;
        if (updater.replaced || !socket) {
            return;
        }
        var now = Date.now();
        if (socket.readyState === WebSocket.OPEN &&
                now - updater.lastMessageAt > updater.staleAfter) {
            updater.dropSocket();
        } else if (socket.readyState === WebSocket.CONNECTING &&
                now - updater.socketStartedAt > updater.connectTimeout) {
            updater.dropSocket();
        }
    },

    startWatchdog: function() {
        if (updater.watchdogTimer === null) {
            updater.watchdogTimer = setInterval(updater.checkConnection, 1000);
        }
    },

    handleMessage: function(jsondata) {
        switch (jsondata.message) {
            case "PLAYER_STATE":
                updater.connectionRestored();
                updater.updatePlayerState(JSON.parse(jsondata.text));
                break;
            case "NO_PLAYER":
                updater.connectionRestored();
                updater.showNoPlayer();
                break;
            case "HEARTBEAT":
                break;
            default:
                console.log("Unknown message:", jsondata.message);
        }
    },

    updatePlayerState: function(state) {
        // Update player name or final answer
        var nameElement = document.getElementById("player-name");
        var nameBox = document.getElementById("name-box");
        var logoElement = document.getElementById("logo");
        
        // Check if we should show final answer (takes priority over name)
        if (state.finalanswer !== undefined && state.finalanswer !== null && state.finalanswer !== "") {
            nameBox.classList.remove("no-player");
            logoElement.style.display = "none";
            nameElement.style.display = "block";
            nameElement.textContent = state.finalanswer;
        } else if (state.name) {
            nameBox.classList.remove("no-player");
            logoElement.style.display = "none";
            nameElement.style.display = "block";
            if (state.name.substring(0, 21) === "data:image/png;base64") {
                // It's a signature image. Build the element directly so the
                // name is never parsed as HTML.
                var image = document.createElement("img");
                image.src = state.name;
                image.alt = "Player Signature";
                nameElement.replaceChildren(image);
            } else {
                nameElement.textContent = state.name;
            }
        } else {
            nameBox.classList.add("no-player");
            nameElement.textContent = "";
            nameElement.style.display = "none";
            logoElement.style.display = "block";
        }

        // Update score
        var scoreElement = document.getElementById("player-score");
        var score = state.score || 0;
        scoreElement.textContent = "$" + score.toLocaleString();
        
        // Update score color based on positive/negative
        if (score < 0) {
            scoreElement.classList.add("negative");
        } else {
            scoreElement.classList.remove("negative");
        }
        
        // Apply extra-condensed font if score has 6 digits
        var absScore = Math.abs(score);
        var digitCount = absScore.toString().length;
        if (digitCount >= 6) {
            scoreElement.classList.add("condensed");
        } else {
            scoreElement.classList.remove("condensed");
        }

        // Update answering box
        var answeringBox = document.getElementById("answering-box");
        if (state.active) {
            answeringBox.classList.add("active");
        } else {
            answeringBox.classList.remove("active");
        }

        // Update lights animation
        if (state.buzzed && !this.lightsRunning) {
            this.runLights();
        } else if (!state.buzzed && this.lightsRunning) {
            this.stopLights();
        }
    },

    runLights: function() {
        if (this.lightsRunning) {
            return;
        }
        this.lightsRunning = true;
        this.currentLightStage = 0;
        var self = this;
        
        // Clear all lights first
        var lights = document.querySelectorAll('.light');
        lights.forEach(function(light) {
            light.classList.remove('active');
        });

        // Light pattern: center (5), then center 3 (4-6), then center 5 (3-7), then center 7 (2-8), then all 9
        var lightPatterns = [
            [1, 2, 3, 4, 5, 6, 7, 8, 9], // Stage 5: all 9
            [2, 3, 4, 5, 6, 7, 8], // Stage 4: center 7
            [3, 4, 5, 6, 7], // Stage 3: center 5
            [4, 5, 6],     // Stage 2: center 3
            [5],           // Stage 1: center light
            [],            // Stage 0: no lights
        ];

        function applyCurrentLightStage() {
            if (self.currentLightStage >= lightPatterns.length) {
                clearInterval(self.lightsInterval);
                self.lightsInterval = null;
                return;
            }

            // Clear all lights before drawing the next countdown frame.
            lights.forEach(function(light) {
                light.classList.remove('active');
            });

            var currentPattern = lightPatterns[self.currentLightStage];
            currentPattern.forEach(function(lightNum) {
                var lightToActivate = document.querySelector('.light[data-light="' + lightNum + '"]');
                if (lightToActivate) {
                    lightToActivate.classList.add('active');
                }
            });

            self.currentLightStage++;
        }

        // Draw the first frame immediately so the red countdown begins with buzz-in.
        applyCurrentLightStage();
        this.lightsInterval = setInterval(function() {
            applyCurrentLightStage();
        }, 1000); // 1 second per stage, matching PlayerWidget timing
    },

    stopLights: function() {
        if (this.lightsInterval) {
            clearInterval(this.lightsInterval);
            this.lightsInterval = null;
        }
        this.lightsRunning = false;
        this.currentLightStage = 0;
        var lights = document.querySelectorAll('.light');
        lights.forEach(function(light) {
            light.classList.remove('active');
        });
    },

    showNoPlayer: function() {
        var nameElement = document.getElementById("player-name");
        var nameBox = document.getElementById("name-box");
        var logoElement = document.getElementById("logo");
        nameBox.classList.add("no-player");
        nameElement.textContent = "";
        nameElement.style.display = "none";
        logoElement.style.display = "block";
        var scoreElement = document.getElementById("player-score");
        scoreElement.textContent = "$0";
        scoreElement.classList.remove("condensed");
        scoreElement.classList.remove("negative");
        document.getElementById("answering-box").classList.remove("active");
        this.stopLights();
    },

    handleReconnect: function() {
        if (updater.reconnectTimer !== null) {
            return;
        }
        // Retry forever: the page may sit through a JParty restart or a long
        // break. Waits double from reconnectDelay up to maxReconnectDelay.
        var delay = Math.min(
            updater.reconnectDelay * Math.pow(2, updater.reconnectAttempts),
            updater.maxReconnectDelay
        );
        updater.reconnectAttempts++;
        console.log("Reconnecting in " + delay + " ms (try " + updater.reconnectAttempts + ")");
        updater.reconnectTimer = setTimeout(function() {
            updater.reconnectTimer = null;
            updater.start();
        }, delay);
    }
};

function positionAnsweringBox() {
    var lightsContainer = document.getElementById('lights-container');
    var scoreBox = document.getElementById('score-box');
    var answeringBox = document.getElementById('answering-box');
    var nameBox = document.getElementById('name-box');
    
    if (!lightsContainer || !scoreBox || !answeringBox || !nameBox) {
        return;
    }
    
    // Target position: 13.5/28.1 of screen height (this is where the border should be)
    var targetBorderPosition = (13.5 / 28.1) * window.innerHeight;
    
    // Get actual heights after layout
    var lightsHeight = lightsContainer.offsetHeight;
    var scoreHeight = scoreBox.offsetHeight;
    
    // Calculate answering box height so that lights + score + answering = target position
    var answeringBoxHeight = targetBorderPosition - lightsHeight - scoreHeight;
    
    // Ensure minimum height
    if (answeringBoxHeight > 50) {
        answeringBox.style.height = answeringBoxHeight + 'px';
    } else {
        answeringBox.style.height = '50px';
    }
    
    // Verify the border is at the right position (for debugging)
    var actualBorderPosition = lightsHeight + scoreHeight + answeringBox.offsetHeight;
    console.log('Target border position: ' + targetBorderPosition + 'px, Actual: ' + actualBorderPosition + 'px');
}

function startLectern() {
    updater.start();
    updater.startWatchdog();

    // Position answering box initially and on resize
    setTimeout(function() {
        positionAnsweringBox();
    }, 100);
    
    window.addEventListener('resize', function() {
        setTimeout(positionAnsweringBox, 50);
    });
    
    // Handle page visibility changes to reconnect if needed
    document.addEventListener("visibilitychange", function() {
        if (!document.hidden && !updater.replaced && !updater.isConnectingOrConnected()) {
            console.log("Page visible, checking connection...");
            updater.start();
        }
        setTimeout(positionAnsweringBox, 100);
    });
}

// No jQuery here: the page has to start even when the laptop can't reach the
// internet.
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", startLectern);
} else {
    startLectern();
}

