// De controlekamer als Mac-app: een zijbalk met projecten, en de pagina's van
// controlroom.py in een WKWebView. De app start de Python-server zelf en stopt
// hem bij afsluiten. Geen Xcode-project: ./build.sh maakt de .app met swiftc.
//
// Projecten staan in ~/.config/ai-layer-kit/projects.json:
//   { "kit": "~/ai-layer-kit", "projecten": { "Durabo": "~/durabo-platform/layers.json" } }

import SwiftUI
import WebKit

let PORT = 7415

struct Config: Decodable {
    var kit: String
    var projecten: [String: String]
}

@MainActor
final class Model: NSObject, ObservableObject, WKNavigationDelegate {
    @Published var projecten: [String] = []
    @Published var gekozen: String? = nil
    @Published var pagina = "/"          // "/" = controlekamer, "/flow" = stroom
    @Published var status = "geen project"
    var paden: [String: String] = [:]
    var kit = ""
    var proces: Process?
    // De webview leeft op het model, niet in de view: SwiftUI maakt views opnieuw
    // en een WKWebView die meegemaakt wordt verliest zijn lading en zijn delegate.
    let web = WKWebView()

    override init() {
        super.init()
        web.navigationDelegate = self
        laadConfig()
    }

    func laadConfig() {
        let pad = ("~/.config/ai-layer-kit/projects.json" as NSString).expandingTildeInPath
        guard let data = FileManager.default.contents(atPath: pad),
              let cfg = try? JSONDecoder().decode(Config.self, from: data) else {
            status = "projects.json ontbreekt of is onleesbaar"; return
        }
        kit = (cfg.kit as NSString).expandingTildeInPath
        paden = cfg.projecten.mapValues { ($0 as NSString).expandingTildeInPath }
        projecten = cfg.projecten.keys.sorted()
    }

    func kies(_ naam: String) {
        guard let manifest = paden[naam] else { return }
        gekozen = naam
        stop()
        let p = Process()
        // Een GUI-app krijgt een kaal PATH; zoek python3.12 daarom zelf op.
        let kandidaten = ["/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12",
                          "/opt/homebrew/bin/python3.12", "/usr/local/bin/python3.12"]
        guard let python = kandidaten.first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else {
            status = "python3.12 niet gevonden"; return
        }
        p.executableURL = URL(fileURLWithPath: python)
        p.arguments = ["controlroom.py", manifest, "--serve"]
        p.currentDirectoryURL = URL(fileURLWithPath: kit)
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        do { try p.run() } catch { status = "kan de server niet starten: \(error)"; return }
        proces = p
        status = "server start…"
        wachtOpServer(pogingen: 40)
    }

    func wachtOpServer(pogingen: Int) {
        guard pogingen > 0 else { status = "server antwoordt niet op :\(PORT)"; return }
        var req = URLRequest(url: URL(string: "http://127.0.0.1:\(PORT)/meet.json")!)
        req.timeoutInterval = 0.5
        URLSession.shared.dataTask(with: req) { _, resp, _ in
            Task { @MainActor in
                if (resp as? HTTPURLResponse)?.statusCode == 200 {
                    self.status = "\(self.gekozen ?? "") · :\(PORT)"
                    self.laad()
                } else {
                    try? await Task.sleep(nanoseconds: 250_000_000)
                    self.wachtOpServer(pogingen: pogingen - 1)
                }
            }
        }.resume()
    }

    func laad() {
        web.load(URLRequest(url: URL(string: "http://127.0.0.1:\(PORT)\(pagina)")!))
    }

    func stop() {
        proces?.terminate()
        proces = nil
    }

    nonisolated func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        Task { @MainActor in self.status = "laden mislukt: \(error.localizedDescription)" }
    }
}

struct Web: NSViewRepresentable {
    let web: WKWebView
    func makeNSView(context: Context) -> WKWebView { web }
    func updateNSView(_ nsView: WKWebView, context: Context) {}
}

struct Venster: View {
    @EnvironmentObject var model: Model
    var body: some View {
        NavigationSplitView {
            List(model.projecten, id: \.self, selection: Binding(
                get: { model.gekozen },
                set: { if let n = $0 { model.kies(n) } })) { naam in
                Label(naam, systemImage: "square.stack.3d.up")
            }
            .navigationTitle("Projecten")
            .navigationSplitViewColumnWidth(min: 160, ideal: 200)
        } detail: {
            VStack(spacing: 0) {
                Picker("", selection: $model.pagina) {
                    Text("Controlekamer").tag("/")
                    Text("Stroom").tag("/flow")
                }
                .pickerStyle(.segmented)
                .padding(8)
                .onChange(of: model.pagina) { _, _ in if model.gekozen != nil { model.laad() } }
                Divider()
                if model.gekozen == nil {
                    Spacer()
                    Text("Kies een project").foregroundStyle(.secondary)
                    Spacer()
                } else {
                    Web(web: model.web)
                }
                Divider()
                Text(model.status)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 10).padding(.vertical, 4)
            }
        }
        .frame(minWidth: 1100, minHeight: 720)
    }
}

final class Delegate: NSObject, NSApplicationDelegate {
    var model: Model?
    func applicationWillTerminate(_ notification: Notification) {
        Task { @MainActor in model?.stop() }
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

@main
struct ControlRoomApp: App {
    @NSApplicationDelegateAdaptor(Delegate.self) var delegate
    @StateObject var model = Model()
    var body: some Scene {
        WindowGroup("Controlekamer") {
            Venster()
                .environmentObject(model)
                .onAppear {
                    delegate.model = model
                    if model.projecten.count == 1, let n = model.projecten.first { model.kies(n) }
                }
        }
    }
}
