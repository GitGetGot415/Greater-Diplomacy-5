package org.greaterdiplomacy.gd5;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Build;
import android.os.Bundle;
import android.util.Log;
import android.view.View;
import android.view.WindowInsets;
import android.view.inputmethod.InputMethodManager;
import android.webkit.ConsoleMessage;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.window.OnBackInvokedDispatcher;

import androidx.webkit.WebViewAssetLoader;

import java.util.Collections;

/** Runs the same game archive and browser storage as the web distribution. */
public final class MainActivity extends Activity {
    private static final String TAG = "GD5WebView";
    private static final String GAME_URL =
        "https://appassets.androidplatform.net/assets/www/index.html";
    private WebView game;
    private boolean keyboardVisible;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        game = new WebView(this);
        setContentView(game);
        WebSettings settings = game.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMediaPlaybackRequiresUserGesture(false);
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);

        WebViewAssetLoader loader = new WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", new WebViewAssetLoader.AssetsPathHandler(this))
            .build();
        // Preserve Pygbag's relative imports and package URLs while serving its
        // entire runtime from the APK, including on the first launch offline.
        WebViewAssetLoader.AssetsPathHandler runtimeAssets = new WebViewAssetLoader.AssetsPathHandler(this);
        WebViewAssetLoader runtimeLoader = new WebViewAssetLoader.Builder()
            .setDomain("pygame-web.github.io")
            .addPathHandler("/cdn/", path -> {
                // NumPy's wheel URL can contain a second slash after /cdn/.
                WebResourceResponse response = runtimeAssets.handle("runtime/" + path.replaceAll("^/+", ""));
                if (response != null) {
                    response.setResponseHeaders(Collections.singletonMap("Access-Control-Allow-Origin", "*"));
                    if (path.endsWith(".wasm")) response.setMimeType("application/wasm");
                }
                return response;
            })
            .build();
        game.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(
                    WebView view, WebResourceRequest request) {
                WebResourceResponse response = runtimeLoader.shouldInterceptRequest(request.getUrl());
                return response != null ? response : loader.shouldInterceptRequest(request.getUrl());
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                // Top-level navigation stays in GD5; the version check can use the network.
                return !request.getUrl().toString().equals(GAME_URL);
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request,
                                        WebResourceError error) {
                Log.e(TAG, request.getUrl() + ": " + error.getDescription());
            }
        });
        game.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onConsoleMessage(ConsoleMessage message) {
                Log.i(TAG, message.message());
                return true;
            }
        });
        game.addJavascriptInterface(new Keyboard(), "GD5Android");
        if (Build.VERSION.SDK_INT >= 30) {
            // The back gesture and the keyboard's hide key close the keyboard
            // without the game. Report the close so the focused text box
            // unfocuses. ui/mobile_keyboard.py ignores the report after the
            // game's own hideKeyboard(). Android 8-10 have no keyboard
            // visibility signal, so there a text box stays focused until tapped away.
            game.setOnApplyWindowInsetsListener((view, insets) -> {
                boolean visible = insets.isVisible(WindowInsets.Type.ime());
                if (keyboardVisible && !visible) {
                    game.evaluateJavascript(
                        "window.__gd5_keyboard && window.__gd5_keyboard.dismissed()", null);
                }
                keyboardVisible = visible;
                // Keep the WebView's own handling of insets.
                return view.onApplyWindowInsets(insets);
            });
        }
        if (Build.VERSION.SDK_INT >= 33) {
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(
                OnBackInvokedDispatcher.PRIORITY_DEFAULT, this::confirmExit);
        }
        game.loadUrl(GAME_URL);
    }

    /**
     * Opens and closes the on-screen keyboard for ui/mobile_keyboard.py.
     *
     * The WebView opens the keyboard for a focused text box only when the
     * focus happens during a tap. The game focuses its hidden text box a frame
     * after the tap, so the game asks Android directly. JavaScript calls these
     * methods on a background thread; the keyboard calls run on the UI thread.
     */
    private final class Keyboard {
        @JavascriptInterface
        public void showKeyboard() {
            game.post(() -> {
                game.requestFocus();
                InputMethodManager keyboard = (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
                keyboard.showSoftInput(game, 0);
            });
        }

        @JavascriptInterface
        public void hideKeyboard() {
            game.post(() -> {
                InputMethodManager keyboard = (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
                keyboard.hideSoftInputFromWindow(game.getWindowToken(), 0);
            });
        }
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) {
            getWindow().getDecorView().setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION);
        }
    }

    @Override
    public void onBackPressed() {
        confirmExit();
    }

    private void confirmExit() {
        // Back must not navigate out of the game and discard its in-memory state.
        new AlertDialog.Builder(this)
            .setMessage("Exit Greater Diplomacy 5?")
            .setPositiveButton("Exit", (dialog, which) -> finish())
            .setNegativeButton("Cancel", null)
            .show();
    }

    @Override
    protected void onPause() {
        game.onPause();
        game.pauseTimers();
        super.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        game.resumeTimers();
        game.onResume();
    }

    @Override
    protected void onDestroy() {
        game.destroy();
        super.onDestroy();
    }
}
