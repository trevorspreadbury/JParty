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
        // No seat yet: the seat picker is showing and connects once one is
        // chosen.
        if (updater.playerNumber === null) {
            return;
        }
        var url = "ws://" + location.host + "/lecternsocket?player=" + updater.playerNumber;
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
        if (!updater.socket) {
            return;
        }
        console.log("Lectern connection went quiet, reconnecting");
        updater.detachSocket();
        updater.connectionLost();
    },

    // Close the current socket without anything reacting to it closing.
    detachSocket: function() {
        var socket = updater.socket;
        if (!socket) {
            return;
        }
        socket.onopen = null;
        socket.onmessage = null;
        socket.onclose = null;
        socket.onerror = null;
        updater.socket = null;
        try {
            socket.close();
        } catch (error) {
            console.error("Error closing socket:", error);
        }
    },

    // Show a different seat on this lectern, without reloading the page so
    // full screen is kept. The choice is saved in the URL and in this
    // browser, so a refresh or the next visit opens the same seat.
    switchSeat: function(seat) {
        if (seat === updater.playerNumber && !updater.replaced &&
                updater.isConnectingOrConnected()) {
            return;
        }
        updater.detachSocket();
        if (updater.reconnectTimer !== null) {
            clearTimeout(updater.reconnectTimer);
            updater.reconnectTimer = null;
        }
        updater.connectionRestored();
        updater.reconnectAttempts = 0;
        updater.replaced = false;
        updater.playerNumber = seat;
        lecternSettings.save("seat", String(seat));
        lecternSettings.setUrlParam("player", String(seat));
        updater.showNoPlayer();
        updater.start();
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

// Settings remembered by this browser, so a lectern laptop opens the same
// seat and rotation next time, and the same values kept in the URL so a
// refresh or bookmark keeps them too.
var lecternSettings = {
    prefix: "jparty-lectern-",

    load: function(key) {
        try {
            return window.localStorage.getItem(lecternSettings.prefix + key);
        } catch (error) {
            return null;
        }
    },

    save: function(key, value) {
        try {
            window.localStorage.setItem(lecternSettings.prefix + key, value);
        } catch (error) {
            console.error("Could not save lectern setting " + key, error);
        }
    },

    urlParam: function(name) {
        return new URLSearchParams(window.location.search).get(name);
    },

    setUrlParam: function(name, value) {
        var url = new URL(window.location.href);
        url.searchParams.set(name, value);
        window.history.replaceState(null, "", url.toString());
    }
};

// Keyboard controls, rotation, full screen, the seat picker and the hidden
// cursor. Everything works from the keyboard, because the mouse is hard to
// find on a laptop tucked behind a lectern.
var lecternControls = {
    rotations: [0, 90, 180, 270],
    rotation: 0,
    // Hide the cursor after this long without the mouse moving.
    cursorHideAfter: 2000,
    cursorTimer: null,
    toastTimer: null,
    toastDuration: 5000,

    // Read a rotation from the URL or settings: 0, 90, 180 or 270 degrees
    // clockwise. "right" and "left" mean a quarter turn each way.
    parseRotation: function(text) {
        if (text === null || text === undefined) {
            return null;
        }
        var aliases = {right: 90, left: 270};
        var value = aliases[String(text).toLowerCase()];
        if (value === undefined) {
            value = parseInt(text, 10);
        }
        return lecternControls.rotations.indexOf(value) === -1 ? null : value;
    },

    // Seats are zero-based in the URL (player=0 is lectern 1).
    parseSeat: function(text) {
        if (text === null || text === undefined || !/^\d+$/.test(String(text))) {
            return null;
        }
        var seat = parseInt(text, 10);
        return seat < maxPlayers ? seat : null;
    },

    setRotation: function(degrees) {
        lecternControls.rotation = degrees;
        var body = document.body;
        lecternControls.rotations.forEach(function(value) {
            body.classList.remove("rotate-" + value);
        });
        if (degrees !== 0) {
            body.classList.add("rotate-" + degrees);
        }
        lecternSettings.save("rotate", String(degrees));
        lecternSettings.setUrlParam("rotate", String(degrees));
        setTimeout(positionAnsweringBox, 50);
    },

    // R turns the lectern a quarter turn clockwise; Shift+R turns it back.
    rotate: function(step) {
        var list = lecternControls.rotations;
        var index = list.indexOf(lecternControls.rotation);
        var next = list[(index + step + list.length) % list.length];
        lecternControls.setRotation(next);
    },

    isFullscreen: function() {
        return !!(document.fullscreenElement || document.webkitFullscreenElement);
    },

    // Browsers only allow full screen in answer to a key press or click,
    // which is why this is on the F key.
    toggleFullscreen: function() {
        var result;
        try {
            if (lecternControls.isFullscreen()) {
                var exit = document.exitFullscreen || document.webkitExitFullscreen;
                result = exit.call(document);
            } else {
                var root = document.documentElement;
                var request = root.requestFullscreen || root.webkitRequestFullscreen;
                result = request.call(root);
            }
        } catch (error) {
            console.error("Full screen failed:", error);
            return;
        }
        if (result && typeof result.catch === "function") {
            result.catch(function(error) {
                console.error("Full screen failed:", error);
            });
        }
    },

    showCursor: function() {
        document.body.classList.remove("cursor-hidden");
        if (lecternControls.cursorTimer !== null) {
            clearTimeout(lecternControls.cursorTimer);
        }
        lecternControls.cursorTimer = setTimeout(function() {
            lecternControls.cursorTimer = null;
            document.body.classList.add("cursor-hidden");
        }, lecternControls.cursorHideAfter);
    },

    // Fill ``element`` with one hint per key.
    showKeyHelp: function(element) {
        var hints = [
            "F: full screen",
            "R: rotate",
            "1–" + maxPlayers + ": change lectern"
        ];
        element.replaceChildren();
        hints.forEach(function(hint) {
            var span = document.createElement("span");
            span.textContent = hint;
            element.appendChild(span);
        });
    },

    // Show which lectern this is, with the keys, for a few seconds.
    showToast: function() {
        if (updater.playerNumber === null) {
            return;
        }
        document.getElementById("lectern-toast-seat").textContent =
            "Lectern " + (updater.playerNumber + 1);
        lecternControls.showKeyHelp(document.getElementById("lectern-key-help"));
        var toast = document.getElementById("lectern-toast");
        toast.style.display = "";
        if (lecternControls.toastTimer !== null) {
            clearTimeout(lecternControls.toastTimer);
        }
        lecternControls.toastTimer = setTimeout(function() {
            lecternControls.toastTimer = null;
            toast.style.display = "none";
        }, lecternControls.toastDuration);
    },

    showSeatPicker: function() {
        var buttons = document.getElementById("seat-picker-buttons");
        buttons.replaceChildren();
        for (var seat = 0; seat < maxPlayers; seat++) {
            var button = document.createElement("button");
            button.type = "button";
            button.textContent = String(seat + 1);
            button.dataset.seat = String(seat);
            button.addEventListener("click", function(event) {
                lecternControls.chooseSeat(parseInt(event.currentTarget.dataset.seat, 10));
            });
            buttons.appendChild(button);
        }
        lecternControls.showKeyHelp(document.getElementById("seat-picker-key-help"));
        document.getElementById("seat-picker").style.display = "";
    },

    hideSeatPicker: function() {
        document.getElementById("seat-picker").style.display = "none";
    },

    chooseSeat: function(seat) {
        lecternControls.hideSeatPicker();
        updater.switchSeat(seat);
        lecternControls.showToast();
    },

    onKeyDown: function(event) {
        if (event.ctrlKey || event.metaKey || event.altKey) {
            return;
        }
        var key = event.key;
        if (key === "f" || key === "F") {
            event.preventDefault();
            lecternControls.toggleFullscreen();
        } else if (key === "r" || key === "R") {
            event.preventDefault();
            lecternControls.rotate(event.shiftKey ? -1 : 1);
        } else if (/^[1-9]$/.test(key) && parseInt(key, 10) <= maxPlayers) {
            event.preventDefault();
            lecternControls.chooseSeat(parseInt(key, 10) - 1);
        } else if (key === "?" || key === "h" || key === "H") {
            lecternControls.showToast();
        }
    },

    // Pick the seat and rotation: the URL first, then what this browser
    // used last. With no seat at all, ask for one.
    init: function() {
        var rotation = lecternControls.parseRotation(lecternSettings.urlParam("rotate"));
        if (rotation === null) {
            rotation = lecternControls.parseRotation(lecternSettings.load("rotate"));
        }
        lecternControls.setRotation(rotation === null ? 0 : rotation);

        var seat = typeof playerNumber === "number" ? playerNumber : null;
        if (seat === null) {
            seat = lecternControls.parseSeat(lecternSettings.load("seat"));
        }
        document.addEventListener("keydown", lecternControls.onKeyDown);
        document.addEventListener("mousemove", lecternControls.showCursor);
        lecternControls.showCursor();
        if (seat === null) {
            lecternControls.showSeatPicker();
            return;
        }
        updater.playerNumber = seat;
        lecternSettings.save("seat", String(seat));
        lecternSettings.setUrlParam("player", String(seat));
        lecternControls.showToast();
    }
};

function positionAnsweringBox() {
    var container = document.getElementById('lectern-container');
    var lightsContainer = document.getElementById('lights-container');
    var scoreBox = document.getElementById('score-box');
    var answeringBox = document.getElementById('answering-box');
    var nameBox = document.getElementById('name-box');

    if (!container || !lightsContainer || !scoreBox || !answeringBox || !nameBox) {
        return;
    }

    // The bottom of the answering box sits 13.5/28.1 of the way down the
    // lectern. The lectern box's own height is used, not the window's,
    // because a turned lectern is as tall as the window is wide.
    var targetBorderPosition = (13.5 / 28.1) * container.clientHeight;

    var lightsHeight = lightsContainer.offsetHeight;
    var scoreHeight = scoreBox.offsetHeight;
    var answeringBoxHeight = targetBorderPosition - lightsHeight - scoreHeight;

    if (answeringBoxHeight > 50) {
        answeringBox.style.height = answeringBoxHeight + 'px';
    } else {
        answeringBox.style.height = '50px';
    }
}

function startLectern() {
    lecternControls.init();
    updater.start();
    updater.startWatchdog();

    // Position answering box initially and on resize
    setTimeout(positionAnsweringBox, 100);

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
