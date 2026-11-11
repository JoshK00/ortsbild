//
//  DashboardView.swift
//  Ortsbild
//

import SwiftUI
import WebKit

/// Where the dashboard is and what the app lets its web view do. Pure functions, so they can be tested.
nonisolated enum DashboardRoute {
    /// What to do with a link that the user taps inside the dashboard.
    enum Navigation: Equatable {
        /// Stays in the web view: it is our own host.
        case allow
        /// Opens in Safari (or the mail app): somebody else's page. The dashboard itself loads nothing from other hosts.
        case external
        /// Nothing happens (`javascript:`, `file:` and other schemes).
        case cancel
    }

    /// The page keeps its own look inside the app: `?app=1` tells it that it sits in the app (no browser header).
    static let appQuery = URLQueryItem(name: "app", value: "1")
    /// A case id is hex (the backend hashes the report id). Anything else is dropped, so nothing odd gets into the address.
    private static let caseIDCharacters = CharacterSet(charactersIn: "0123456789abcdef")

    /// `https://<host>/dashboard/?app=1`, with `#case=<id>` to open one case.
    static func url(base: URL = AppConfig.backendURL, caseID: String? = nil) -> URL {
        var components = URLComponents(url: base, resolvingAgainstBaseURL: false) ?? URLComponents()
        components.path = "/dashboard/"
        components.queryItems = [appQuery]
        if let caseID, isValid(caseID: caseID) { components.fragment = "case=\(caseID)" }
        return components.url ?? base
    }

    static func isValid(caseID: String) -> Bool {
        (1...64).contains(caseID.count) && caseID.unicodeScalars.allSatisfy(caseIDCharacters.contains)
    }

    /// Only the host of our backend stays in the app, other web links open outside.
    static func navigation(for url: URL, base: URL = AppConfig.backendURL) -> Navigation {
        guard let scheme = url.scheme?.lowercased() else { return .cancel }
        if scheme == "about" { return url.absoluteString == "about:blank" ? .allow : .cancel }
        switch scheme {
        case "https", "http":
            guard let host = url.host?.lowercased() else { return .cancel }
            // Same host over https stays. The same host over plain http is not served by us, so it is not trusted either.
            return scheme == "https" && host == base.host?.lowercased() ? .allow : .external
        case "mailto", "tel":
            return .external
        default:
            return .cancel
        }
    }

    /// After a while away the page is loaded again, so the list is not hours old when the user comes back to the tab.
    static let reloadAfter: TimeInterval = 60

    static func needsReload(leftAt: Date?, now: Date = Date()) -> Bool {
        guard let leftAt else { return false }
        return now.timeIntervalSince(leftAt) > reloadAfter
    }

    /// The honest German text for a page that did not load.
    static func message(for error: Error) -> String {
        if let error = error as? URLError {
            switch error.code {
            case .notConnectedToInternet, .networkConnectionLost, .dataNotAllowed:
                return "Du bist offline. Das Dashboard braucht eine Internetverbindung."
            case .timedOut:
                return "Der Server antwortet nicht. Bitte versuche es gleich noch einmal."
            default: break
            }
        }
        return "Das Dashboard konnte nicht geladen werden."
    }

    static func message(forHTTPStatus status: Int) -> String {
        status == 404
            ? "Das Dashboard ist auf dem Server noch nicht verfügbar."
            : "Der Server meldet einen Fehler (\(status)). Bitte versuche es später noch einmal."
    }
}

/// The dashboard as a tab: the same page that the browser shows, in a web view that stays on our own host.
struct DashboardView: View {
    @Environment(AppNavigation.self) private var navigation

    /// The page is created when the tab is opened the first time, so the app does not load it at launch.
    @State private var hasBeenOpened = false
    @State private var phase: DashboardPhase = .loading
    @State private var reloadToken = 0
    @State private var leftAt: Date?

    var body: some View {
        ZStack {
            DashboardTheme.background.ignoresSafeArea()
            if hasBeenOpened {
                DashboardWebView(
                    url: DashboardRoute.url(caseID: navigation.dashboardCaseID),
                    reloadToken: reloadToken,
                    phase: $phase
                )
                // The page paints under the status bar and handles env(safe-area-inset-top) itself. The bottom is the tab bar.
                .ignoresSafeArea(.container, edges: .top)
                .accessibilityLabel("Dashboard mit Karte und Liste der gemeldeten Mängel")
            }
            switch phase {
            case .loading:
                ProgressView()
                    .controlSize(.large)
                    .tint(.white)
                    .accessibilityLabel("Dashboard wird geladen")
            case .failed(let message):
                DashboardError(message: message, retry: reload)
            case .loaded:
                EmptyView()
            }
        }
        .onAppear { hasBeenOpened = true }
        .onChange(of: navigation.selectedTab) { old, new in
            if old == .dashboard { leftAt = Date() }
            if new == .dashboard, DashboardRoute.needsReload(leftAt: leftAt) { reload() }
            if new == .dashboard { leftAt = nil }
        }
    }

    private func reload() {
        phase = .loading
        reloadToken += 1
    }
}

enum DashboardPhase: Equatable {
    case loading
    case loaded
    case failed(String)
}

/// The colour of the dashboard page (`body` in `backend/dashboard/style.css`), so no white flash shows before the page is painted.
// TODO: Keep in sync with the background of the dashboard stylesheet.
enum DashboardTheme {
    static let background = Color(red: 0x14 / 255, green: 0x18 / 255, blue: 0x1f / 255)
    static let backgroundUIColor = UIColor(red: 0x14 / 255, green: 0x18 / 255, blue: 0x1f / 255, alpha: 1)
}

private struct DashboardError: View {
    let message: String
    let retry: () -> Void

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "wifi.exclamationmark")
                .font(.largeTitle)
                .foregroundStyle(.secondary)
                .accessibilityHidden(true)
            Text(message)
                .font(.body)
                .multilineTextAlignment(.center)
                .foregroundStyle(.white)
            Button("Erneut versuchen", action: retry)
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
        }
        .padding(32)
    }
}

/// The web view. It loads `url`, tells the phase to its owner and sends links to other hosts to Safari.
private struct DashboardWebView: UIViewRepresentable {
    let url: URL
    let reloadToken: Int
    @Binding var phase: DashboardPhase

    func makeCoordinator() -> Coordinator { Coordinator(phase: $phase) }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.defaultWebpagePreferences.allowsContentJavaScript = true
        configuration.applicationNameForUserAgent = "OrtsbildApp"  // the page can tell that it runs in the app
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = false
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        webView.scrollView.bounces = false
        // Two fingers zoom the map inside the page, not the web view itself (otherwise the page and the map fight over the gesture)
        webView.scrollView.minimumZoomScale = 1
        webView.scrollView.maximumZoomScale = 1
        webView.isOpaque = false
        webView.backgroundColor = DashboardTheme.backgroundUIColor
        webView.scrollView.backgroundColor = DashboardTheme.backgroundUIColor
        webView.accessibilityLabel = "Dashboard"
        #if DEBUG
        webView.isInspectable = true
        #endif
        context.coordinator.requestedURL = url
        context.coordinator.reloadToken = reloadToken
        webView.load(URLRequest(url: url))
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        let coordinator = context.coordinator
        if coordinator.reloadToken != reloadToken {
            // "Erneut versuchen" or back after a while: a fresh load of the page
            coordinator.reloadToken = reloadToken
            coordinator.requestedURL = url
            webView.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData))
        } else if coordinator.requestedURL != url {
            // Another case: only the part after # differs, the page stays and shows the case (hashchange)
            coordinator.requestedURL = url
            webView.load(URLRequest(url: url))
        }
    }

    final class Coordinator: NSObject, WKNavigationDelegate {
        @Binding var phase: DashboardPhase
        var requestedURL: URL?
        var reloadToken = 0

        init(phase: Binding<DashboardPhase>) {
            _phase = phase
        }

        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction) async -> WKNavigationActionPolicy {
            guard let url = navigationAction.request.url else { return .cancel }
            switch DashboardRoute.navigation(for: url) {
            case .allow:
                return .allow
            case .external:
                // Only a tap of the user opens another app, a page cannot open one by itself
                if navigationAction.navigationType == .linkActivated || navigationAction.targetFrame == nil {
                    await UIApplication.shared.open(url)
                }
                return .cancel
            case .cancel:
                return .cancel
            }
        }

        func webView(_ webView: WKWebView, decidePolicyFor navigationResponse: WKNavigationResponse) async -> WKNavigationResponsePolicy {
            if navigationResponse.isForMainFrame, let http = navigationResponse.response as? HTTPURLResponse, http.statusCode >= 400 {
                phase = .failed(DashboardRoute.message(forHTTPStatus: http.statusCode))
                return .cancel
            }
            return .allow
        }

        func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
            if phase != .loaded { phase = .loading }
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            phase = .loaded
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            report(error)
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            report(error)
        }

        private func report(_ error: Error) {
            // A load that was replaced by another one (-999) is no failure
            if (error as? URLError)?.code == .cancelled { return }
            phase = .failed(DashboardRoute.message(for: error))
        }
    }
}

#Preview {
    DashboardView()
        .environment(AppNavigation())
}
