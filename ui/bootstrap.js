// Use a fresh module URL on each page load so WebView2 cannot reuse an older app.js.
import(`./app.js?v=${Date.now()}`);
