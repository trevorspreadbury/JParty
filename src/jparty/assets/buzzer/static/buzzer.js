

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

var last_buzz = new Date().getTime();

async function buzz() {
    if (!$("#buzzer").prop("disabled")) {
        send("BUZZ");
        $("#buzzer").prop("disabled", true);

        setTimeout(function () {
            $("#buzzer").prop("disabled", false);
        }, 250);
    };
}

var current_page = "";
function load_page(pagename) {
    console.log("loading page "+pagename);
    if (!!current_page) {
        console.log("hiding page "+current_page);
        $("."+current_page+"-page").hide();
    }
    try {
        if (pagename !== null && pagename != "null") {
            console.log("showing page "+pagename);
            $("."+pagename+"-page").show();
        }
    } catch {
        console.log("failed");
        return 1;
    }
    current_page = pagename;
    return 0;
}

function setToken(token) {
  var d = new Date();
  d.setTime(d.getTime() + (24*60*60*1000)); // lasts 24 hour
  var expires = "expires="+ d.toUTCString();
  document.cookie = "token=" + token + ";" + expires + ";path=/";
}

function getToken() {
  var name = "token=";
  var decodedCookie = decodeURIComponent(document.cookie);
  var ca = decodedCookie.split(';');
  for(var i = 0; i <ca.length; i++) {
    var c = ca[i];
    while (c.charAt(0) == ' ') {
      c = c.substring(1);
    }
    if (c.indexOf(name) == 0) {
      return c.substring(name.length, c.length);
    }
  }
  return "";
}

function clearToken() {
    document.cookie = "token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;";
}

function send(msg, text="") {
    var message = {message:msg, text: text};
    updater.socket.send(JSON.stringify(message));
}
function wagerForm() {
    var amount =$("input[name='wager']").val().replace(/[\s,]/g, '');
    if (amount != "") {
        send("WAGER", amount);
        load_page(null);
    }
    return false;
}
function answerForm() {
    var answer = $("input[name='answer']").val();
    send("ANSWER",answer);
    document.activeElement.blur();
    load_page(null);
    return false;
}

// True from sending a name until the server answers, so a double-tap on
// "Play!" sends only one name.
var joining = false;

function setJoining(value) {
    joining = value;
    $("#submit-button").prop("disabled", value);
    $("#prompt-button").prop("disabled", value);
}

function nameForm(name) {
    if (joining) {
        return;
    }
    console.log(name);
    setJoining(true);
    send("NAME",name);
}

function renderSavedPlayerChoices(payload) {
    var choicesContainer = document.getElementById("saved-player-choices");
    var hint = document.getElementById("chooser-hint");
    if (!choicesContainer || !payload) {
        return;
    }
    choicesContainer.innerHTML = "";
    hint.textContent = "Select your saved player (" + payload.claimed_count + "/" + payload.total_count + " claimed)";
    (payload.players || []).forEach(function(player) {
        var button = document.createElement("button");
        button.type = "button";
        button.className = "jparty-button saved-player-button";
        if (player.claimed) {
            button.classList.add("claimed");
        }
        button.disabled = !!player.claimed;
        if ((player.name || "").substring(0, 21) === "data:image/png;base64") {
            var image = document.createElement("img");
            image.src = player.name;
            image.alt = "Saved player " + player.player_number;
            image.className = "saved-player-signature";
            button.appendChild(image);
        } else {
            button.textContent = player.name;
        }
        button.addEventListener("click", function() {
            send("CLAIM_PLAYER", String(player.player_number));
        });
        choicesContainer.appendChild(button);
    });
}

function renderPickBoard(board) {
    // Draw the clues left on the board; a played clue leaves a gap.
    var container = document.getElementById("pick-board");
    container.innerHTML = "";
    if (!board) {
        return;
    }
    var categories = board.categories || [];
    container.style.setProperty("--pick-columns", Math.max(categories.length, 1));
    categories.forEach(function(category) {
        var label = document.createElement("div");
        label.className = "pick-category";
        label.textContent = category;
        container.appendChild(label);
    });
    (board.rows || []).forEach(function(values, row) {
        values.forEach(function(value, column) {
            var button = document.createElement("button");
            button.type = "button";
            button.className = "pick-value";
            if (value === null) {
                button.disabled = true;
                button.textContent = "";
            } else {
                button.textContent = "$" + value;
                button.addEventListener("click", function() {
                    // One pick per turn: the game offers the board again if
                    // it can't use this one.
                    $(".pick-value").prop("disabled", true);
                    send("PICK", column + "," + row);
                    load_page(null);
                });
            }
            container.appendChild(button);
        });
    });
}

function showDailyDoubleWager(bounds) {
    $("input[name='wager']").val("");
    $(".wager_input").attr("min", bounds.min);
    $(".wager_input").attr("max", bounds.max);
    document.getElementById("dd-hint").textContent =
        "Daily Double! Wager $" + bounds.min + " to $" + bounds.max;
    load_page("ddwager");
}

function showPage(state) {
    // Redraw the page a reconnecting phone was on, with what it needs.
    if (state.page === "pick") {
        renderPickBoard(state.page_data);
    }
    if (state.page === "ddwager" && state.page_data) {
        showDailyDoubleWager(state.page_data);
        return;
    }
    load_page(state.page);
}

function set_max_wager(score) {
    $(".wager_input").attr("max", Math.max(0, score));
    $(".wager_input").attr("min",0);
    console.log("Max wager:" + $(".wager_input").attr("max"));
}

const padding = 2;
const canvasratio = 1.3422;

var signaturePad;

function resizeCanvas() {
    const ratio =  Math.max(window.devicePixelRatio || 1, 1);
    const canvas = document.querySelector("canvas");
    canvas.width = canvas.offsetWidth * ratio;
    canvas.height = canvas.width / canvasratio;
    canvas.getContext("2d").scale(ratio, ratio);
    signaturePad.clear(); // otherwise isEmpty() might return incorrect value
}


$(document).ready(function() {
    if (!window.console) window.console = {};
    if (!window.console.log) window.console.log = function() {};

    updater.start();

    const canvas = document.querySelector("canvas");
    canvas.style.width = "100%";

    signaturePad = new SignaturePad(canvas, {
        penColor: "#ffffff",
        backgroundColor: "#1010a1"
    });


    window.addEventListener("resize", resizeCanvas);
    // resizeCanvas();

    var cookie = getToken();
    if (cookie != "") {
        console.log("checking token "+cookie)
        updater.socket.onopen = function (event) {
            updater.socket.send(JSON.stringify({message:"CHECK_IF_EXISTS", text:cookie}));
        };
    } else {
        console.log("no cookie")
        load_page("name");
        resizeCanvas();
    };


    $("#clear-button").on("click", function () {
        signaturePad.clear()
    });

    $("#undo-button").on("click", function () {
        const data = signaturePad.toData();

        if (data) {
            data.pop(); // remove the last dot or line
            signaturePad.fromData(data);
        }
    });

    $("#prompt-button").on("click", function () {
        let name = prompt("Enter name", "");
        if (name != null) {
            nameForm(name);
        };
    });

    $("#submit-button").on("click", function () {
        if (!signaturePad.isEmpty()) {
            let image = signaturePad.toDataURL();
            console.log(image);
            nameForm(image);
        };
    });
});





var updater = {
    socket: null,
    // Close code the server sends when this player reconnects from another
    // tab or screen. Keep in step with BUZZER_REPLACED_CLOSE_CODE in
    // handlers.py.
    replacedCloseCode: 4001,

    start: function() {
        var url = "ws://" + location.host + "/buzzersocket";
        updater.socket = new WebSocket(url);
        updater.socket.onclose = function(event) {
            if (event.code === updater.replacedCloseCode) {
                // Reloading here would take the player back from the other
                // tab, which would then reload too, forever. Stay closed and
                // let the player choose this tab again by hand.
                load_page("replaced");
                return;
            }
            location.reload(true);
        };
        updater.socket.onmessage = function(event) {
            jsondata = JSON.parse(event.data);
            switch (jsondata.message) {
                case "FULL":
                case "GAMEFULL":
                    alert("Game has too many players!")
                    window.location.reload()
                    break;
                case "GAMESTARTED":
                    alert("Game has started!")
                    setJoining(false);
                    break;
                case "TOKEN":
                    load_page("buzz");
                    setToken(jsondata.text);
                    break;
                case "CLAIMED":
                    var claimData = JSON.parse(jsondata.text);
                    setToken(claimData.token);
                    set_max_wager(claimData.state.score);
                    showPage(claimData.state);
                    break;
                case "NEW":
                    setJoining(false);
                    load_page("name");
                    resizeCanvas();
                    break;
                case "SHOW_CHOOSER":
                    setJoining(false);
                    clearToken();
                    renderSavedPlayerChoices(JSON.parse(jsondata.text));
                    load_page("chooser");
                    break;
                case "EXISTS":
                    console.log("Already exists" + jsondata.text);
                    state = JSON.parse(jsondata.text);
                    set_max_wager(state.score);
                    showPage(state);
                    break;
                case "PLAYER_TAKEN":
                    alert("That saved player has already been claimed.");
                    break;
                case "ALL_CLAIMED":
                    setJoining(false);
                    clearToken();
                    alert("All saved players have already been claimed.");
                    load_page(null);
                    break;
                case "LOGOUT":
                    setJoining(false);
                    clearToken();
                    load_page(null);
                    break;
                case "PROMPTWAGER":
                    // A new prompt starts empty, so a game with several
                    // Finals never resends the previous Final's wager.
                    $("input[name='wager']").val("");
                    document.getElementById("dd-hint").textContent = "";
                    set_max_wager(jsondata.text);
                    load_page("wager");
                    break;
                case "PROMPTPICK":
                    renderPickBoard(JSON.parse(jsondata.text));
                    load_page("pick");
                    break;
                case "PROMPTDDWAGER":
                    showDailyDoubleWager(JSON.parse(jsondata.text));
                    break;
                case "PROMPTANSWER":
                    // Likewise, clear the previous Final's answer. EXISTS
                    // (a reconnect) keeps what the player has typed so far.
                    $("input[name='answer']").val("");
                    load_page("answer");
                    break;
                case "TOOLATE":
                    answerForm();
                    break;
                case "SHOW_PAGE":
                    // Sent when a tiebreaker starts or ends, so only the
                    // tied players see the buzz button.
                    load_page(jsondata.text);
                    break;
            }
        }
    }
};



