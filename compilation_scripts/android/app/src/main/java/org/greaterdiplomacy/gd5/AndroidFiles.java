package org.greaterdiplomacy.gd5;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.net.Uri;
import android.util.Base64;
import android.util.Log;
import android.webkit.JavascriptInterface;
import android.webkit.MimeTypeMap;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebView;

import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.file.Files;
import java.util.Locale;

/** User-selected documents only; game saves keep using the shared web storage. */
public final class AndroidFiles {
    private static final int IMPORT_REQUEST = 1;
    private static final int EXPORT_REQUEST = 2;
    private static final String TAG = "GD5Files";
    private final Activity activity;
    private final WebView game;
    private ValueCallback<Uri[]> importCallback;
    private PendingExport pending;
    private boolean closed;

    private static final class PendingExport {
        final String id;
        final String name;
        final File file;
        final OutputStream stream;
        boolean choosing;
        boolean copying;

        PendingExport(String id, String name, File file, OutputStream stream) {
            this.id = id;
            this.name = name;
            this.file = file;
            this.stream = stream;
        }
    }

    AndroidFiles(Activity activity, WebView game) {
        this.activity = activity;
        this.game = game;
    }

    boolean chooseImport(ValueCallback<Uri[]> callback, WebChromeClient.FileChooserParams params) {
        if (importCallback != null) importCallback.onReceiveValue(null);
        importCallback = callback;
        try {
            activity.startActivityForResult(params.createIntent(), IMPORT_REQUEST);
        } catch (ActivityNotFoundException | SecurityException error) {
            importCallback = null;
            callback.onReceiveValue(null);
            new AlertDialog.Builder(activity).setTitle("Import Error")
                .setMessage("Could not open the Android file picker: " + error.getMessage())
                .setPositiveButton("OK", null).show();
        }
        return true;
    }

    boolean onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == IMPORT_REQUEST) {
            ValueCallback<Uri[]> callback = importCallback;
            importCallback = null;
            Uri[] uris = WebChromeClient.FileChooserParams.parseResult(resultCode, data);
            // Never pass a file:// URI from another app to the WebView's private files.
            if (uris != null) {
                for (Uri uri : uris) {
                    if (uri == null || !"content".equals(uri.getScheme())) {
                        uris = null;
                        break;
                    }
                }
            }
            if (callback != null) callback.onReceiveValue(uris);
            return true;
        }
        if (requestCode != EXPORT_REQUEST) return false;
        synchronized (this) {
            PendingExport request = pending;
            if (request == null || !request.choosing || request.copying) return true;
            Uri destination = data == null ? null : data.getData();
            if (resultCode != Activity.RESULT_OK || destination == null) {
                complete(request, "cancelled", "");
            } else if (!"content".equals(destination.getScheme())) {
                complete(request, "error", "The selected destination is not an Android document.");
            } else {
                request.copying = true;
                // A cloud document provider can block; keep writes off the game/UI thread.
                new Thread(() -> copyExport(request, destination), "GD5FileExport").start();
            }
        }
        return true;
    }

    @JavascriptInterface
    public synchronized boolean beginExport(String id, String name) {
        if (closed) return false;
        if (pending != null) {
            report(id, "error", "Finish the current export before starting another.");
            return false;
        }
        File file = null;
        try {
            file = File.createTempFile("gd5-export-", ".tmp", activity.getCacheDir());
            pending = new PendingExport(id, name, file, new FileOutputStream(file));
            return true;
        } catch (IOException | SecurityException error) {
            if (file != null) file.delete();
            report(id, "error", "Could not prepare the export: " + error.getMessage());
            return false;
        }
    }

    @JavascriptInterface
    public synchronized boolean appendExport(String id, String encoded) {
        if (pending == null || !pending.id.equals(id) || pending.choosing) return false;
        try {
            pending.stream.write(Base64.decode(encoded, Base64.DEFAULT));
            return true;
        } catch (IOException | IllegalArgumentException error) {
            complete(pending, "error", "Could not prepare the export: " + error.getMessage());
            return false;
        }
    }

    @JavascriptInterface
    public synchronized void finishExport(String id) {
        if (pending == null || !pending.id.equals(id) || pending.choosing) return;
        PendingExport request = pending;
        try {
            request.stream.close();
        } catch (IOException error) {
            complete(request, "error", "Could not prepare the export: " + error.getMessage());
            return;
        }
        request.choosing = true;
        activity.runOnUiThread(() -> chooseExport(request));
    }

    private synchronized void chooseExport(PendingExport request) {
        if (closed || pending != request) return;
        String extension = request.name.substring(request.name.lastIndexOf('.') + 1).toLowerCase(Locale.ROOT);
        String mime = MimeTypeMap.getSingleton().getMimeTypeFromExtension(extension);
        Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
            .setType(mime == null ? "application/octet-stream" : mime).putExtra(Intent.EXTRA_TITLE, request.name);
        try {
            activity.startActivityForResult(intent, EXPORT_REQUEST);
        } catch (ActivityNotFoundException | SecurityException error) {
            complete(request, "error", "Could not open the Android file picker: " + error.getMessage());
        }
    }

    private void copyExport(PendingExport request, Uri destination) {
        String status = "saved";
        String message = "";
        try (OutputStream output = activity.getContentResolver().openOutputStream(destination, "wt")) {
            if (output == null) throw new IOException("The selected document cannot be opened for writing.");
            Files.copy(request.file.toPath(), output);
        } catch (IOException | SecurityException error) {
            status = "error";
            message = "Could not write the export: " + error.getMessage();
        }
        complete(request, status, message);
    }

    @JavascriptInterface
    public synchronized void cancelExport(String id) {
        if (pending != null && pending.id.equals(id) && !pending.copying) complete(pending, "cancelled", "");
    }

    private synchronized void complete(PendingExport request, String status, String message) {
        try {
            request.stream.close();
        } catch (IOException error) {
            Log.w(TAG, "Could not close export staging file", error);
        }
        if (!request.file.delete()) Log.w(TAG, "Could not remove export staging file");
        if (pending == request) pending = null;
        if (!closed) report(request.id, status, message);
    }

    private void report(String id, String status, String message) {
        String script = "window.__gd5_download_done(" + JSONObject.quote(id) + ","
            + JSONObject.quote(status) + "," + JSONObject.quote(message) + ")";
        game.post(() -> {
            if (!activity.isDestroyed()) game.evaluateJavascript(script, null);
        });
    }

    synchronized void close() {
        closed = true;
        if (importCallback != null) importCallback.onReceiveValue(null);
        importCallback = null;
        if (pending != null && !pending.copying) complete(pending, "cancelled", "");
    }
}
