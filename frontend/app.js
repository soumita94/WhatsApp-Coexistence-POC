// ============================================================
// AXIOM — WhatsApp Coexistence POC
// app.js
//
// SECURITY RULES (enforced here):
//   - App Secret is NEVER in this file.
//   - System User token is NEVER in this file.
//   - Authorization codes are sent only to the backend,
//     never stored in localStorage or logged.
// ============================================================

"use strict";

// ------------------------------------------------------------
// Application state
// ------------------------------------------------------------

let metaConfig = null;
let facebookSDKReady = false;


// ------------------------------------------------------------
// UI helpers
// ------------------------------------------------------------

function setStatus(text, type) {
    // type: "loading" | "ready" | "error" | "success" | "info"
    const el = document.getElementById("status");
    const textEl = document.getElementById("status-text");

    el.className = "status status-" + (type || "info");
    textEl.textContent = text;
}

function setButtonEnabled(enabled) {
    const btn = document.getElementById("connect-whatsapp");
    btn.disabled = !enabled;
}

function showResult(data) {
    const card = document.getElementById("result-card");
    const pre = document.getElementById("result");

    // NEVER put access_token, app_secret, etc. in the result display.
    // Backend already strips them; this is a belt-and-suspenders filter.
    const safe = JSON.parse(JSON.stringify(data));
    delete safe.access_token;
    delete safe.token;

    card.classList.remove("hidden");
    pre.textContent = JSON.stringify(safe, null, 2);
}


// ------------------------------------------------------------
// Load public configuration from FastAPI
// ------------------------------------------------------------

async function loadConfig() {
    const response = await fetch("/api/config");

    if (!response.ok) {
        throw new Error(
            `Failed to load application configuration (HTTP ${response.status}).`
        );
    }

    metaConfig = await response.json();

    // Validate that required public fields are present
    if (!metaConfig.meta_app_id) {
        throw new Error(
            "Backend /api/config did not return META_APP_ID. " +
            "Check that .env is loaded by Uvicorn from the backend directory."
        );
    }

    if (!metaConfig.meta_config_id) {
        throw new Error(
            "Backend /api/config did not return META_CONFIG_ID. " +
            "Check .env."
        );
    }

    console.log(
        "[AXIOM] Public Meta config loaded:",
        {
            meta_app_id: metaConfig.meta_app_id,
            meta_config_id: metaConfig.meta_config_id,
            meta_graph_version: metaConfig.meta_graph_version,
        }
    );
}


// ------------------------------------------------------------
// Initialize Facebook SDK
//
// Called either from _onFBSDKLoaded (SDK finished before config)
// or from initAfterConfig (config finished before SDK).
// Only runs once — guarded by facebookSDKReady.
// ------------------------------------------------------------

function initFacebookSDK() {
    if (facebookSDKReady) {
        // Already initialized — nothing to do.
        return;
    }

    if (!window.FB) {
        // SDK script not yet available — _onFBSDKLoaded will call us.
        console.log("[AXIOM] SDK object not yet available, waiting...");
        return;
    }

    if (!metaConfig || !metaConfig.meta_app_id) {
        // Config not yet loaded — initAfterConfig() will call us.
        console.log("[AXIOM] Config not yet loaded, waiting for config...");
        return;
    }

    FB.init({
        appId:   metaConfig.meta_app_id,
        cookie:  true,
        xfbml:   true,
        version: metaConfig.meta_graph_version || "v25.0",
    });

    facebookSDKReady = true;

    console.log("[AXIOM] Facebook SDK initialized successfully.");
    setStatus("Facebook SDK ready. Click Connect WhatsApp to begin.", "ready");
    setButtonEnabled(true);
}


// ------------------------------------------------------------
// Called once config is loaded.
// At this point, the SDK may or may not have loaded yet.
// ------------------------------------------------------------

function initAfterConfig() {
    if (window._fbSDKLoaded && window.FB) {
        // SDK already ready — initialize now.
        initFacebookSDK();
    } else if (window._fbSDKError) {
        // SDK script failed to load.
        setStatus(
            "Failed to load Meta Facebook SDK. " +
            "Check your network connection or ad-blocker.",
            "error"
        );
    } else {
        // SDK hasn't loaded yet. Register the deferred callback so the
        // inline fbAsyncInit (defined in index.html) will trigger it.
        console.log("[AXIOM] Config ready, waiting for SDK to finish loading...");
        setStatus("Loading Meta SDK...", "loading");

        window._onFBSDKLoaded = function () {
            console.log("[AXIOM] SDK finished loading (deferred callback).");
            initFacebookSDK();
        };

        // Guard against the race where fbAsyncInit fired between the
        // `_fbSDKLoaded` check above and the `_onFBSDKLoaded` assignment
        // just made. If the flag is now true, call the handler directly.
        if (window._fbSDKLoaded && window.FB) {
            console.log("[AXIOM] Race guard: SDK became ready during callback registration.");
            window._onFBSDKLoaded();
        }
    }
}


// ------------------------------------------------------------
// Register SDK error handler (SDK script onerror handler in HTML
// sets window._fbSDKError; this handles the timing where config
// finishes after the error fires).
// ------------------------------------------------------------

window._onFBSDKError = function () {
    console.error("[AXIOM] Meta Facebook SDK script failed to load.");
    setStatus(
        "Failed to load Meta Facebook SDK. " +
        "Check your network or disable ad-blockers.",
        "error"
    );
    setButtonEnabled(false);
};


// ------------------------------------------------------------
// Listen for Embedded Signup postMessage events
//
// Meta sends WA_EMBEDDED_SIGNUP messages from the popup.
// We must handle them whether or not FB.login callback fires.
// ------------------------------------------------------------

window.addEventListener(
    "message",
    function (event) {
        // Only accept messages from Meta domains
        if (
            !event.origin.includes("facebook.com") &&
            !event.origin.includes("meta.com")
        ) {
            return;
        }

        let data;

        try {
            data =
                typeof event.data === "string"
                    ? JSON.parse(event.data)
                    : event.data;
        } catch {
            return;
        }

        if (data.type !== "WA_EMBEDDED_SIGNUP") {
            return;
        }

        console.log(
            "[AXIOM] WA_EMBEDDED_SIGNUP event received:",
            // Log event type and WABA id (if present) but NOT auth codes or tokens.
            {
                event: data.event,
                waba_id: data.data?.waba_id,
                phone_number_id: data.data?.phone_number_id,
            }
        );

        handleEmbeddedSignupEvent(data);
    }
);


// ------------------------------------------------------------
// Handle Meta Embedded Signup postMessage events
// ------------------------------------------------------------

function handleEmbeddedSignupEvent(eventData) {
    setStatus("Meta signup event: " + eventData.event, "info");

    if (eventData.event === "CANCEL") {
        setStatus("Signup cancelled by user.", "info");
        setButtonEnabled(true);
        return;
    }

    if (eventData.event === "ERROR") {
        setStatus(
            "Meta signup returned an error: " +
            JSON.stringify(eventData.data || eventData),
            "error"
        );
        setButtonEnabled(true);
        return;
    }

    if (eventData.event === "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING") {
        setStatus(
            "Coexistence onboarding completed. Finalizing with backend...",
            "info"
        );
        // Store non-sensitive WABA/phone info for later backend call.
        // The authorization code comes separately through the FB.login callback.
        window._latestSignupEventData = {
            event: eventData.event,
            waba_id: eventData.data?.waba_id || null,
            phone_number_id: eventData.data?.phone_number_id || null,
        };
        return;
    }

    // Other intermediate events — just log them.
    console.log("[AXIOM] Unhandled Embedded Signup event:", eventData.event);
}


// ------------------------------------------------------------
// Launch Embedded Signup
//
// CRITICAL: FB.login() MUST be called synchronously in the
// click handler. Any await before FB.login() causes the browser
// to treat the popup as unsolicited → blocked.
// ------------------------------------------------------------

function connectWhatsApp() {
    if (!metaConfig) {
        setStatus("Configuration not loaded. Please refresh.", "error");
        return;
    }

    if (!facebookSDKReady) {
        setStatus("Facebook SDK is not ready yet. Please wait.", "error");
        return;
    }

    if (!metaConfig.meta_config_id) {
        setStatus(
            "META_CONFIG_ID is missing from backend config. Check .env.",
            "error"
        );
        return;
    }

    // ----------------------------------------------------------------
    // HTTPS GUARD — Meta's Facebook SDK refuses FB.login() on plain
    // HTTP pages since 2018. Detect this early and give a clear error
    // instead of a confusing "popup closed" message.
    // ----------------------------------------------------------------
    if (window.location.protocol !== "https:") {
        setStatus(
            "HTTPS required: Meta's SDK will not open the signup popup " +
            "on a plain HTTP page. Run the server with TLS (see gen_dev_cert.py) " +
            "and open https://127.0.0.1:8000 instead.",
            "error"
        );
        console.error(
            "[AXIOM] FB.login() requires HTTPS. " +
            "Current protocol:", window.location.protocol
        );
        return;
    }

    setButtonEnabled(false);
    setStatus("Opening Meta Embedded Signup...", "loading");

    // ----------------------------------------------------------------
    // FB.login is called SYNCHRONOUSLY from the user click — no await
    // before this point. This is required to avoid popup blocking.
    //
    // featureType: "whatsapp_business_app_onboarding" directs Meta to
    // use the Coexistence onboarding path instead of the standard
    // API-only registration path.
    // ----------------------------------------------------------------

    FB.login(
        function (response) {
            console.log(
                "[AXIOM] FB.login callback received",
                // Do NOT log response.authResponse.code — that is secret.
                { status: response.status }
            );

            if (!response || !response.authResponse) {
                const status = response?.status || "unknown";
                setButtonEnabled(true);

                if (status === "unknown") {
                    setStatus("Signup cancelled or popup closed.", "info");
                } else {
                    setStatus(
                        "Meta authorization failed or cancelled (status: " +
                        status + ").",
                        "info"
                    );
                }
                return;
            }

            // response.authResponse.code is the authorization code.
            // We extract it here but DO NOT display or log it.
            const code = response.authResponse.code;

            if (!code) {
                setStatus(
                    "Meta returned a login response but no authorization code. " +
                    "Check that response_type: 'code' is configured.",
                    "error"
                );
                setButtonEnabled(true);
                return;
            }

            // ✅ Embedded Signup returned successfully.
            // The code is not logged or displayed — backend only.
            console.log(
                "[AXIOM] Embedded Signup completed successfully. " +
                "Authorization code received (not logged)."
            );
            setStatus(
                "Embedded Signup returned successfully. Sending to backend...",
                "loading"
            );

            // Pass the code to the backend. The WA_EMBEDDED_SIGNUP event
            // data (waba_id, etc.) may have arrived via postMessage already
            // and is stored in window._latestSignupEventData.
            completeOnboarding(code);
        },
        {
            config_id: metaConfig.meta_config_id,

            response_type: "code",

            override_default_response_type: true,

            extras: {
                // This is the key that tells Meta this is a
                // Coexistence / Business App onboarding flow,
                // NOT a standard API-only registration.
                featureType: "whatsapp_business_app_onboarding",

                // sessionInfoVersion: "3" enables the structured
                // WA_EMBEDDED_SIGNUP postMessage events.
                sessionInfoVersion: "3",
            },
        }
    );
}


// ------------------------------------------------------------
// Send authorization code to backend for exchange
// ------------------------------------------------------------

async function completeOnboarding(code) {
    const signupEventData = window._latestSignupEventData || {};

    try {
        const response = await fetch("/api/onboarding/complete", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                // Authorization code — backend exchanges this.
                // It is sent over localhost HTTPS-equivalent;
                // never stored client-side beyond this call.
                code: code,

                // Safe, non-secret WABA metadata from the Embedded
                // Signup postMessage event.
                waba_id: signupEventData.waba_id || null,
                phone_number_id: signupEventData.phone_number_id || null,
                signup_event: signupEventData.event || null,
            }),
        });

        const data = await response.json();

        showResult(data);

        if (!response.ok) {
            setStatus(
                "Onboarding failed: " +
                (data.detail?.message || data.detail || "Unknown backend error."),
                "error"
            );
            return;
        }

        setStatus("WhatsApp connected successfully via Coexistence.", "success");

    } catch (error) {
        console.error("[AXIOM] Backend request failed:", error.message);
        setStatus("Backend request failed: " + error.message, "error");

    } finally {
        setButtonEnabled(true);
        window._latestSignupEventData = null;
    }
}


// ------------------------------------------------------------
// Page initialization
// ------------------------------------------------------------

document.addEventListener("DOMContentLoaded", async function () {
    setStatus("Loading configuration...", "loading");
    setButtonEnabled(false);

    try {
        await loadConfig();

        // Wire the click handler AFTER config is confirmed loaded.
        document
            .getElementById("connect-whatsapp")
            .addEventListener("click", connectWhatsApp);

        // Try to initialize the SDK now that config is loaded.
        // If SDK hasn't loaded yet, initAfterConfig registers the
        // deferred _onFBSDKLoaded callback.
        initAfterConfig();

    } catch (error) {
        console.error("[AXIOM] Initialization error:", error.message);
        setStatus("Failed to initialize: " + error.message, "error");
    }
});