// 灵枢桌面版 —— 自带窗口的 Windows 客户端（WinForms + WebView2）
//
// 为什么要有它：控制台是本地 Web 服务，之前只能双击 .cmd / .exe 开个黑窗口，
// 再自己去浏览器里开 127.0.0.1:8010。这对「装成软件给人用」来说缺三样东西：
//   1. 没有自己的窗口 —— 浏览器标签页里夹着一堆别的页面，关标签就等于关服务，
//      地址栏还能被误改成别的站点；
//   2. 环境出问题只有命令行报错，用户看不懂也复制不出来；
//   3. 起服务、等就绪、停服务全靠手工。
// 这个程序把这三件事收进一个窗口：左边是环境自检与一键修复，右边是内嵌的
// WebView2（真正嵌在本进程里的浏览器控件，不是外部标签页），关窗口即停服务。
//
// 语言版本：随 Windows 自带的 csc.exe 只支持到 C# 5，所以这里不用字符串插值、
// 不用 ?. / => 成员、不用 nameof，写法保守一点换来「不需要装 .NET SDK 也能编」。
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace SpiritScoutDesktop
{
    /// <summary>
    /// 把内嵌浏览器需要的三个 DLL 以资源形式塞进 exe，首次运行时解到
    /// %LOCALAPPDATA%\SpiritScout\lib 再从那儿加载——这样发出去就是一个
    /// 独立 exe，不用随包带一堆 DLL，也不会因为 DLL 缺失而白屏。
    /// </summary>
    internal static class Runtime
    {
        private const string ManagedCore = "Microsoft.Web.WebView2.Core.dll";
        private const string ManagedWinForms = "Microsoft.Web.WebView2.WinForms.dll";
        private const string NativeLoader = "WebView2Loader.dll";
        private const string Marker = "1.0.2903.40";   // 与 build-desktop.ps1 里的 SDK 版本一致

        internal static string LibDir { get; private set; }
        internal static string LastError { get; private set; }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool SetDllDirectory(string path);

        internal static void Prepare()
        {
            try
            {
                string baseDir = ResolveLibDir();
                Directory.CreateDirectory(baseDir);
                Extract("wv2.core", Path.Combine(baseDir, ManagedCore));
                Extract("wv2.winforms", Path.Combine(baseDir, ManagedWinForms));
                Extract("wv2.loader", Path.Combine(baseDir, NativeLoader));
                LibDir = baseDir;

                // 关键：用 Load(byte[]) 而不是 LoadFrom。仓库放在桌面同步目录 / 网络盘时，
                // LoadFrom 会被 CLR 判成「从网络位置加载」并抛 0x80131515，表现就是
                // 内嵌浏览器起不来、只剩一个报错框。
                AppDomain.CurrentDomain.AssemblyResolve += delegate(object sender, ResolveEventArgs args)
                {
                    string name = new AssemblyName(args.Name).Name;
                    string path = Path.Combine(baseDir, name + ".dll");
                    if (!File.Exists(path)) { return null; }
                    try { return Assembly.Load(File.ReadAllBytes(path)); }
                    catch (Exception) { return null; }
                };
                SetDllDirectory(baseDir);

                // 预加载一次：窗体类型里有 WebView2 字段，类型加载发生在窗体构造时，
                // 这一步能保证到那时程序集已经在域里了。
                LoadManaged(Path.Combine(baseDir, ManagedCore));
                LoadManaged(Path.Combine(baseDir, ManagedWinForms));
            }
            catch (Exception ex)
            {
                LastError = ex.ToString();
                // 解不出来就没法起内嵌浏览器：把原因写进程序目录，别让人对着白屏猜
                try
                {
                    File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,
                        "desktop-runtime-error.txt"), LastError, Encoding.UTF8);
                }
                catch (Exception) { }
            }
        }

        /// <summary>
        /// 放解压 DLL 的目录。AppData 在部分机器/策略下不可写（实测会抛
        /// UnauthorizedAccessException），所以留三级：AppData → 程序目录 → 临时目录。
        /// 全都不行就抛出去，让上层退到「用浏览器打开」。
        /// </summary>
        private static string ResolveLibDir()
        {
            string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            List<string> probes = new List<string>();
            if (!string.IsNullOrEmpty(localAppData))
            {
                probes.Add(Path.Combine(localAppData, "SpiritScout", "lib", Marker));
            }
            probes.Add(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "灵枢桌面版-lib", Marker));
            probes.Add(Path.Combine(Path.GetTempPath(), "SpiritScout-lib", Marker));

            List<string> errors = new List<string>();
            foreach (string candidate in probes)
            {
                try
                {
                    Directory.CreateDirectory(candidate);
                    string probe = Path.Combine(candidate, ".writable");
                    File.WriteAllText(probe, "ok", Encoding.UTF8);
                    File.Delete(probe);
                    return candidate;
                }
                catch (Exception ex)
                {
                    errors.Add(candidate + " → " + ex.GetType().Name + ": " + ex.Message);
                }
            }
            throw new IOException("三处候选目录都写不进去：" + string.Join(" | ", errors.ToArray()));
        }
        private static readonly List<Assembly> Loaded = new List<Assembly>();

        private static void LoadManaged(string path)
        {
            try
            {
                Loaded.Add(Assembly.Load(File.ReadAllBytes(path)));
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine("预加载失败 " + path + ": " + ex.Message);
            }
        }
        private static void Extract(string resourceName, string target)
        {
            Assembly asm = Assembly.GetExecutingAssembly();
            using (Stream source = asm.GetManifestResourceStream(resourceName))
            {
                if (source == null) { throw new InvalidOperationException("缺资源：" + resourceName); }
                // 大小与长度都一致就跳过，避免每次启动都重写文件
                FileInfo info = new FileInfo(target);
                if (info.Exists && info.Length == source.Length) { return; }
                using (FileStream output = File.Create(target))
                {
                    source.CopyTo(output);
                }
            }
        }
    }

    internal static class Program
    {
        [STAThread]
        private static void Main()
        {
            // 这是个 winexe：崩了既没控制台也没弹窗，用户只看到「双击没反应」。
            // 所以先把兜底挂上，崩了至少留下能看的日志和一句人话。
            AppDomain.CurrentDomain.UnhandledException += OnFatal;
            Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
            Application.ThreadException += OnThreadException;
            try
            {
                Runtime.Prepare();
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new DesktopForm());
            }
            catch (Exception ex)
            {
                Report(ex);
            }
        }

        private static void OnFatal(object sender, UnhandledExceptionEventArgs e)
        {
            Report(e.ExceptionObject as Exception ?? new Exception("未知致命错误"));
        }

        private static void OnThreadException(object sender, ThreadExceptionEventArgs e)
        {
            Report(e.Exception);
        }

        private static void Report(Exception ex)
        {
            string path = "（日志没写成：三处候选目录都不可写）";
            string fileName = "crash-" + DateTime.Now.ToString("yyyyMMdd-HHmmss") + ".log";
            List<string> dirs = new List<string>();
            string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            if (!string.IsNullOrEmpty(localAppData)) { dirs.Add(Path.Combine(localAppData, "SpiritScout", "logs")); }
            dirs.Add(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "logs"));
            dirs.Add(Path.Combine(Path.GetTempPath(), "SpiritScout-logs"));
            foreach (string dir in dirs)
            {
                try
                {
                    Directory.CreateDirectory(dir);
                    string candidate = Path.Combine(dir, fileName);
                    File.WriteAllText(candidate, ex.ToString(), Encoding.UTF8);
                    path = candidate;
                    break;
                }
                catch (Exception) { }
            }
            try
            {
                MessageBox.Show("灵枢桌面版出错了：\n\n" + ex.Message + "\n\n细节写在这里：\n" + path,
                    "灵枢桌面版", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
            catch (Exception) { }
        }
    }

    internal sealed class DesktopForm : Form
    {
        // 控制台默认端口；被占用时自动换一个，不让人去改配置
        private const int PreferredPort = 8010;
        private const string LogFolderName = "logs";

        private readonly string _repoRoot;      // 仓库根（start-local.ps1 所在目录）；便携版是程序目录
        private readonly string _packageDir;    // SpiritScout/（pyproject.toml 与 .venv 在这）；便携版是程序目录
        private readonly string _logDir;
        private readonly string _pythonOverride; // desktop.json 里指定的解释器（便携版内嵌的那个）
        private readonly bool _portable;         // 便携版：依赖已装进内嵌 Python，没有 venv 也没有 bootstrap.py

        private readonly Label _status = new Label();
        private readonly TextBox _log = new TextBox();
        private readonly Panel _logPanel = new Panel();
        private readonly Label _placeholder = new Label();
        private WebView2 _web;          // 延迟创建：内嵌浏览器初始化失败也要能开窗

        private readonly Button _btnCheck = new Button();
        private readonly Button _btnFix = new Button();
        private readonly Button _btnStart = new Button();
        private readonly Button _btnStop = new Button();
        private readonly Button _btnReload = new Button();
        private readonly Button _btnExternal = new Button();
        private readonly Button _btnPassword = new Button();
        private readonly Button _btnLogFolder = new Button();
        private readonly Button _btnToggleLog = new Button();

        private Process _server;
        private int _port = PreferredPort;
        private bool _webReady;
        private bool _closing;
        private readonly object _logLock = new object();

        public DesktopForm()
        {
            // 便携版靠 exe 旁边的 desktop.json 指路：root 是程序目录，python 是内嵌解释器。
            // 没有这个文件就是「仓库里跑」的常规模式。
            DesktopConfig cfg = ReadDesktopConfig();
            if (cfg != null && !string.IsNullOrEmpty(cfg.Root) && Directory.Exists(cfg.Root))
            {
                _repoRoot = cfg.Root;
                // 便携版把 configs/ 放在程序目录；万一有人把整仓塞进来，就认 SpiritScout/ 那层。
                string inner = Path.Combine(cfg.Root, "SpiritScout");
                bool innerHasConfig = File.Exists(Path.Combine(inner, "configs", "system.yaml"));
                _packageDir = innerHasConfig ? inner : cfg.Root;
                _pythonOverride = cfg.Python;
                _portable = true;
                if (cfg.Port > 0) { _port = cfg.Port; }
            }
            else
            {
                _repoRoot = ResolveRepoRoot();
                _packageDir = Path.Combine(_repoRoot, "SpiritScout");
                _pythonOverride = null;
                _portable = false;
            }
            _logDir = Path.Combine(_repoRoot, LogFolderName);

            Text = "灵枢桌面版 · SpiritScout";
            StartPosition = FormStartPosition.CenterScreen;
            MinimumSize = new Size(980, 640);
            Size = new Size(1280, 860);
            BackColor = Color.FromArgb(24, 26, 32);
            Font = new Font("Microsoft YaHei UI", 9F);

            BuildLayout();
            Load += OnLoaded;
            FormClosing += OnClosing;
        }

        private static string ResolveRepoRoot()
        {
            // exe 可能放在仓库根（和 start-local.ps1 同级），也可能被单独拷出去。
            // 先看 exe 所在目录，再看上一级，最后退回当前工作目录。
            string exeDir = Path.GetDirectoryName(Application.ExecutablePath);
            string[] candidates = new string[]
            {
                exeDir,
                Path.GetDirectoryName(exeDir),
                Directory.GetCurrentDirectory(),
            };
            foreach (string dir in candidates)
            {
                if (string.IsNullOrEmpty(dir)) { continue; }
                if (Directory.Exists(Path.Combine(dir, "SpiritScout"))
                    && File.Exists(Path.Combine(dir, "SpiritScout", "pyproject.toml")))
                {
                    return dir;
                }
            }
            return exeDir;
        }

        /// <summary>desktop.json 的内容（便携版用）。字段缺省即视为没配。</summary>
        private sealed class DesktopConfig
        {
            public string Root;
            public string Python;
            public int Port;
        }

        /// <summary>读 exe 旁边的 desktop.json；没有或不合法就返回 null（退回仓库模式）。</summary>
        private static DesktopConfig ReadDesktopConfig()
        {
            string exeDir = Path.GetDirectoryName(Application.ExecutablePath);
            if (string.IsNullOrEmpty(exeDir)) { return null; }
            string path = Path.Combine(exeDir, "desktop.json");
            if (!File.Exists(path)) { return null; }
            string json;
            try { json = File.ReadAllText(path, Encoding.UTF8); }
            catch (Exception) { return null; }

            DesktopConfig cfg = new DesktopConfig();
            string root = JsonField(json, "root");
            if (!string.IsNullOrEmpty(root))
            {
                cfg.Root = Path.IsPathRooted(root) ? root : Path.GetFullPath(Path.Combine(exeDir, root));
            }
            string python = JsonField(json, "python");
            if (!string.IsNullOrEmpty(python))
            {
                cfg.Python = Path.IsPathRooted(python) ? python : Path.GetFullPath(Path.Combine(exeDir, python));
            }
            string port = JsonField(json, "port");
            int parsed;
            if (!string.IsNullOrEmpty(port) && int.TryParse(port, out parsed) && parsed > 0 && parsed < 65536)
            {
                cfg.Port = parsed;
            }
            return cfg;
        }

        /// <summary>够用就好的 JSON 取值：只认一层扁平字符串/数字，不引第三方库。</summary>
        private static string JsonField(string json, string key)
        {
            string quoted = "\"" + Regex.Escape(key) + "\"\\s*:\\s*\"([^\"]*)\"";
            Match m = Regex.Match(json, quoted);
            if (m.Success) { return m.Groups[1].Value; }
            m = Regex.Match(json, "\"" + Regex.Escape(key) + "\"\\s*:\\s*(-?\\d+)");
            return m.Success ? m.Groups[1].Value : null;
        }

        // ---------------- 界面 ----------------

        private void BuildLayout()
        {
            FlowLayoutPanel bar = new FlowLayoutPanel();
            bar.Dock = DockStyle.Top;
            bar.Height = 46;
            bar.Padding = new Padding(8, 8, 8, 0);
            bar.BackColor = Color.FromArgb(32, 35, 43);
            bar.WrapContents = false;

            SetupButton(_btnCheck, "环境自检", delegate { Task ignore = CheckEnvironmentAsync(true); });
            SetupButton(_btnFix, "一键修复", delegate { Task ignore = RunBootstrapAsync("--fix", true); });
            SetupButton(_btnStart, "启动服务", delegate { Task ignore = StartServerAsync(); });
            SetupButton(_btnStop, "停止", delegate { StopServer(true); });
            SetupButton(_btnReload, "刷新页面", delegate { ReloadPage(); });
            SetupButton(_btnExternal, "用浏览器打开", delegate { OpenExternal(); });
            SetupButton(_btnPassword, "设管理员密码", delegate { SetPassword(); });
            SetupButton(_btnLogFolder, "日志目录", delegate { OpenLogFolder(); });
            SetupButton(_btnToggleLog, "隐藏日志", delegate { ToggleLog(); });
            _btnStop.Enabled = false;
            _btnReload.Enabled = false;
            _btnExternal.Enabled = false;

            bar.Controls.Add(_btnCheck);
            bar.Controls.Add(_btnFix);
            bar.Controls.Add(_btnStart);
            bar.Controls.Add(_btnStop);
            bar.Controls.Add(_btnReload);
            bar.Controls.Add(_btnExternal);
            bar.Controls.Add(_btnPassword);
            bar.Controls.Add(_btnLogFolder);
            bar.Controls.Add(_btnToggleLog);

            _status.Dock = DockStyle.Top;
            _status.Height = 28;
            _status.TextAlign = ContentAlignment.MiddleLeft;
            _status.Padding = new Padding(10, 0, 10, 0);
            _status.ForeColor = Color.FromArgb(200, 205, 215);
            _status.BackColor = Color.FromArgb(28, 30, 37);
            _status.Text = "正在检查环境…";

            _placeholder.Dock = DockStyle.Fill;
            _placeholder.TextAlign = ContentAlignment.MiddleCenter;
            _placeholder.Font = new Font("Microsoft YaHei UI", 12F);
            _placeholder.ForeColor = Color.FromArgb(150, 156, 168);
            _placeholder.Text = "控制台还没启动：先点上面的「环境自检」，需要补依赖就点「一键修复」。";

            Panel canvas = new Panel();
            canvas.Dock = DockStyle.Fill;
            canvas.Controls.Add(CreateWebView());
            canvas.Controls.Add(_placeholder);

            _log.Multiline = true;
            _log.ReadOnly = true;
            _log.ScrollBars = ScrollBars.Vertical;
            _log.Dock = DockStyle.Fill;
            _log.BackColor = Color.FromArgb(18, 20, 25);
            _log.ForeColor = Color.FromArgb(190, 196, 206);
            _log.Font = new Font("Consolas", 9F);
            _log.BorderStyle = BorderStyle.None;

            _logPanel.Dock = DockStyle.Bottom;
            _logPanel.Height = 170;
            _logPanel.Padding = new Padding(0);
            _logPanel.Controls.Add(_log);

            Controls.Add(canvas);
            Controls.Add(_logPanel);
            Controls.Add(_status);
            Controls.Add(bar);
        }

        /// <summary>
        /// 单独一个方法建 WebView2：引用 WebView2 类型的代码集中在这里，
        /// 于是「DLL 加载不出来」变成这里抛异常、外面 catch 得到，
        /// 而不是整个 BuildLayout 没能 JIT、窗口都开不起来。
        /// </summary>
        private Control CreateWebView()
        {
            try
            {
                _web = new WebView2();
                _web.Dock = DockStyle.Fill;
                _web.Visible = false;
                return _web;
            }
            catch (Exception ex)
            {
                _web = null;
                AppendLog("[!] 内嵌浏览器控件建不起来：" + ex.Message);
                AppendLog("    退路：用「用浏览器打开」，会在 Edge 的独立窗口里打开控制台。");
                return new Panel();
            }
        }
        private static void SetupButton(Button button, string text, EventHandler onClick)
        {
            button.Text = text;
            button.AutoSize = true;
            button.Height = 28;
            button.FlatStyle = FlatStyle.Flat;
            button.FlatAppearance.BorderColor = Color.FromArgb(70, 76, 90);
            button.BackColor = Color.FromArgb(44, 48, 58);
            button.ForeColor = Color.FromArgb(225, 229, 236);
            button.Margin = new Padding(0, 0, 8, 0);
            button.Click += onClick;
        }

        private void ToggleLog()
        {
            _logPanel.Visible = !_logPanel.Visible;
            _btnToggleLog.Text = _logPanel.Visible ? "隐藏日志" : "显示日志";
        }

        private async void OnLoaded(object sender, EventArgs e)
        {
            AppendLog("灵枢桌面版启动。仓库根：" + _repoRoot);
            try
            {
                await InitWebViewAsync();
                await CheckEnvironmentAsync(false);
            }
            catch (Exception ex)
            {
                AppendLog("[x] 启动自检出错：" + ex.Message);
                SetStatus("启动自检出错：日志里有细节。", Color.FromArgb(235, 120, 120));
            }
        }

        // ---------------- 日志 ----------------

        private void AppendLog(string line)
        {
            if (_closing) { return; }
            if (InvokeRequired)
            {
                try { BeginInvoke(new Action<string>(AppendLog), line); }
                catch (InvalidOperationException) { }
                return;
            }
            string stamp = DateTime.Now.ToString("HH:mm:ss");
            lock (_logLock)
            {
                _log.AppendText("[" + stamp + "] " + line + Environment.NewLine);
                try
                {
                    string path = Path.Combine(_logDir, "desktop-" + DateTime.Now.ToString("yyyyMMdd") + ".log");
                    Directory.CreateDirectory(_logDir);
                    File.AppendAllText(path, "[" + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "] " + line + Environment.NewLine, Encoding.UTF8);
                }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
            }
        }

        private void SetStatus(string text, Color color)
        {
            if (InvokeRequired)
            {
                try { BeginInvoke(new Action<string, Color>(SetStatus), text, color); }
                catch (InvalidOperationException) { }
                return;
            }
            _status.Text = text;
            _status.ForeColor = color;
        }

        private void OpenLogFolder()
        {
            try
            {
                Directory.CreateDirectory(_logDir);
                Process.Start("explorer.exe", "/select,\"" + _logDir + "\"");
            }
            catch (Exception ex) { AppendLog("[x] 打不开日志目录：" + ex.Message); }
        }

        // ---------------- 进程与解释器 ----------------

        private string VenvPython()
        {
            return Path.Combine(_packageDir, ".venv", "Scripts", "python.exe");
        }

        /// <summary>跑 bootstrap.py 用的解释器：优先 venv 里的，否则 desktop.json 指定的，最后找系统 Python。</summary>
        private string PickPythonForBootstrap()
        {
            string venv = VenvPython();
            if (File.Exists(venv)) { return venv; }
            if (!string.IsNullOrEmpty(_pythonOverride) && File.Exists(_pythonOverride)) { return _pythonOverride; }
            string fromEnv = Environment.GetEnvironmentVariable("SPIRITSCOUT_PYTHON");
            if (!string.IsNullOrEmpty(fromEnv) && File.Exists(fromEnv)) { return fromEnv; }
            string[] probes = new string[] { "py -3.11", "py -3", "python", "python3" };
            foreach (string probe in probes)
            {
                string version = RunCapture(probe, "-c \"import sys;print(sys.version_info[:2])\"", 15000);
                if (version != null && version.IndexOf("3.1") >= 0) { return probe; }
            }
            return null;
        }

        /// <summary>同步跑一个短命令拿 stdout；失败返回 null。解释器名字里可能带空格（py -3.11）。</summary>
        private static string RunCapture(string exe, string args, int timeoutMs)
        {
            try
            {
                ProcessStartInfo psi = BuildStartInfo(exe, args);
                psi.RedirectStandardOutput = true;
                psi.RedirectStandardError = true;
                using (Process proc = Process.Start(psi))
                {
                    string stdout = proc.StandardOutput.ReadToEnd();
                    proc.StandardError.ReadToEnd();
                    if (!proc.WaitForExit(timeoutMs))
                    {
                        try { proc.Kill(); } catch (InvalidOperationException) { }
                        return null;
                    }
                    return proc.ExitCode == 0 ? stdout : null;
                }
            }
            catch (Exception) { return null; }
        }

        private static ProcessStartInfo BuildStartInfo(string exe, string args)
        {
            ProcessStartInfo psi;
            int space = exe.IndexOf(' ');
            if (space > 0)
            {
                // "py -3.11" 这类启动器：程序名和参数得分开传
                psi = new ProcessStartInfo(exe.Substring(0, space), exe.Substring(space + 1) + " " + args);
            }
            else
            {
                psi = new ProcessStartInfo(exe, args);
            }
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            psi.StandardOutputEncoding = Encoding.UTF8;
            psi.StandardErrorEncoding = Encoding.UTF8;
            psi.EnvironmentVariables["PYTHONUTF8"] = "1";
            psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            // 便携版自带依赖：别让宿主机 %APPDATA%\Python 里的同名包装进 sys.path
            psi.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
            return psi;
        }

        /// <summary>把一段命令的输出逐行喂给日志框，直到进程退出。</summary>
        private async Task<int> RunStreamingAsync(string exe, string args, string workDir)
        {
            if (exe == null)
            {
                AppendLog("[x] 找不到可用的 Python（需要 3.11+）。装好后重开本程序，或用环境变量 SPIRITSCOUT_PYTHON 指定解释器。");
                return 127;
            }
            ProcessStartInfo psi = BuildStartInfo(exe, args);
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;
            psi.WorkingDirectory = workDir;
            Process proc = new Process();
            proc.StartInfo = psi;
            proc.OutputDataReceived += delegate(object s, DataReceivedEventArgs e)
            {
                if (e.Data != null) { AppendLog(e.Data); }
            };
            proc.ErrorDataReceived += delegate(object s, DataReceivedEventArgs e)
            {
                if (e.Data != null) { AppendLog(e.Data); }
            };
            proc.Start();
            proc.BeginOutputReadLine();
            proc.BeginErrorReadLine();
            await Task.Run(delegate { proc.WaitForExit(); });
            int code = proc.ExitCode;
            proc.Dispose();
            return code;
        }

        // ---------------- 环境自检 / 修复 ----------------

        private async Task CheckEnvironmentAsync(bool verbose)
        {
            SetStatus("正在检查环境…", Color.FromArgb(200, 205, 205));
            string python = PickPythonForBootstrap();
            string script = Path.Combine(_packageDir, "scripts", "bootstrap.py");
            if (!File.Exists(script))
            {
                if (_portable) { await CheckPortableAsync(python, verbose); return; }
                SetStatus("环境自检脚本缺失：" + script, Color.FromArgb(235, 120, 120));
                AppendLog("[x] 找不到 " + script + "，这个程序必须放在仓库里运行。");
                return;
            }
            AppendLog("[>] 环境自检：python scripts/bootstrap.py --json");
            CaptureResult probe = await CaptureAsync(python, "\"" + script + "\" --json", _repoRoot);
            int code = probe.Code;
            SummarizeEnvironment(probe.Output);
            if (code == 0)
            {
                SetStatus("环境就绪：可以启动控制台了。", Color.FromArgb(120, 210, 150));
                _btnStart.Enabled = true;
                _placeholder.Text = "环境就绪，点「启动服务」打开控制台。";
            }
            else
            {
                SetStatus("环境需要修复：点「一键修复」（缺依赖 / venv 未建 / 没有 pip）。", Color.FromArgb(240, 190, 110));
                _btnStart.Enabled = false;
                _placeholder.Text = "环境还没就绪：先点「一键修复」，看日志了解缺什么。";
            }
            if (verbose)
            {
                AppendLog(code == 0 ? "[+] 自检通过" : "[!] 自检未通过（退出码 " + code + "）");
            }
        }

        /// <summary>CaptureAsync 的返回值：async 方法不能带 out 参数，就包一层。</summary>
        private sealed class CaptureResult
        {
            public int Code;
            public string Output = "";
        }

        /// <summary>跑一个命令，把 stdout 收下来（不逐行刷日志），失败信息仍进日志。</summary>
        private async Task<CaptureResult> CaptureAsync(string exe, string args, string workDir)
        {
            CaptureResult result = new CaptureResult();
            if (exe == null)
            {
                AppendLog("[x] 找不到可用的 Python（需要 3.11+）。装好后重开本程序，或用环境变量 SPIRITSCOUT_PYTHON 指定解释器。");
                result.Code = 127;
                return result;
            }
            ProcessStartInfo psi = BuildStartInfo(exe, args);
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;
            psi.WorkingDirectory = workDir;
            Process proc = new Process();
            proc.StartInfo = psi;
            string text = "";
            string err = "";
            try
            {
                proc.Start();
                // 两个流都用同步读，且放到后台线程：在 UI 线程上 ReadToEnd 会卡住窗口，
                // 而同一条流混用同步/异步读会直接抛「不能混合同步操作和异步操作」。
                await Task.Run(delegate
                {
                    text = proc.StandardOutput.ReadToEnd();
                    err = proc.StandardError.ReadToEnd();
                    proc.WaitForExit();
                });
                result.Output = text;
                result.Code = proc.ExitCode;
                if (err.Trim().Length > 0 && result.Code != 0)
                {
                    AppendLog("    " + err.Trim());
                }
            }
            catch (Exception ex)
            {
                AppendLog("[x] 命令跑不起来：" + ex.Message);
                result.Code = 1;
            }
            finally
            {
                try { proc.Dispose(); } catch (Exception) { }
            }
            return result;
        }
        /// <summary>把 bootstrap 的 JSON 翻成一句人话——用户不该去读 JSON。</summary>
        private void SummarizeEnvironment(string json)
        {
            try
            {
                bool ok = Regex.IsMatch(json, "\"ok\"\\s*:\\s*true");
                Match version = Regex.Match(json, "\"python\"\\s*:\\s*\\{[^}]*\"version\"\\s*:\\s*\"([^\"]+)\"");
                string pyVersion = version.Success ? version.Groups[1].Value : "未知";
                Match missing = Regex.Match(json, "\"missing\"\\s*:\\s*\\[([^\\]]*)\\]");
                string miss = missing.Success ? missing.Groups[1].Value.Trim() : "";
                Match warns = Regex.Match(json, "\"warnings\"\\s*:\\s*\\[([^\\]]*)\\]");
                AppendLog((ok ? "[+] 环境就绪" : "[!] 环境未就绪")
                          + "：Python " + pyVersion
                          + "，缺依赖 " + (miss.Length == 0 ? "0 个" : CountItems(miss) + " 个"));
                if (miss.Length > 0) { AppendLog("    缺：" + miss.Replace("\"", "").Replace(",", " ")); }
                if (warns.Success && warns.Groups[1].Value.Trim().Length > 0)
                {
                    AppendLog("    提醒：" + warns.Groups[1].Value.Replace("\"", "").Replace(",", "；"));
                }
            }
            catch (Exception ex) { AppendLog("[!] 自检结果解析失败：" + ex.Message); }
        }

        private static int CountItems(string csv)
        {
            int count = 0;
            foreach (string part in csv.Split(','))
            {
                if (part.Trim().Length > 0) { count++; }
            }
            return count;
        }
        /// <summary>便携版体检：依赖装在内嵌解释器里，问一句就知道，不需要 bootstrap.py。</summary>
        private async Task CheckPortableAsync(string python, bool verbose)
        {
            if (python == null || !File.Exists(python))
            {
                SetStatus("找不到内嵌的 Python：desktop.json 里的 python 路径不对。", Color.FromArgb(235, 120, 120));
                AppendLog("[x] desktop.json 指向的解释器不存在；便携版要整份目录一起拷，不能只拿 exe。");
                _btnStart.Enabled = false;
                return;
            }
            AppendLog("[>] 便携版自检：" + python);
            CaptureResult probe = await CaptureAsync(python,
                "-c \"import sys, spiritscout; print(spiritscout.__version__ + ' | ' + sys.version.split()[0])\"",
                _packageDir);
            string text = probe.Output == null ? "" : probe.Output.Trim();
            if (probe.Code == 0 && text.Length > 0)
            {
                string[] parts = text.Split('|');
                string pkg = parts[0].Trim();
                string py = parts.Length > 1 ? parts[1].Trim() : "?";
                AppendLog("[+] 内嵌运行时可用：灵枢 " + pkg + "，Python " + py);
                SetStatus("环境就绪（便携版，无需安装）：可以启动控制台了。", Color.FromArgb(120, 210, 150));
                _btnStart.Enabled = true;
                _placeholder.Text = "环境就绪，点「启动服务」打开控制台。";
            }
            else
            {
                SetStatus("便携版环境不完整：建议重新解压整份目录。", Color.FromArgb(240, 190, 110));
                _btnStart.Enabled = false;
                AppendLog("[!] 内嵌解释器里 import spiritscout 失败（退出码 " + probe.Code + "）");
            }
            if (verbose) { AppendLog(probe.Code == 0 ? "[+] 便携版自检通过" : "[!] 便携版自检未通过"); }
        }

        private async Task RunBootstrapAsync(string extraArgs, bool thenCheck)
        {
            if (_portable)
            {
                // 便携版没有 venv 也没有 bootstrap.py：依赖关系在打包时就装进内嵌解释器了。
                SetStatus("便携版不需要修复：依赖已随包装好，坏了就重新解压整份目录。", Color.FromArgb(200, 205, 205));
                AppendLog("[i] 便携版的 Python 与依赖都在程序目录里，没有 venv 可修。");
                if (thenCheck) { await CheckEnvironmentAsync(false); }
                return;
            }
            _btnFix.Enabled = false;
            _btnCheck.Enabled = false;
            SetStatus("正在修复环境（首次装依赖要几分钟，别关窗口）…", Color.FromArgb(240, 190, 110));
            string python = PickPythonForBootstrap();
            string script = Path.Combine(_packageDir, "scripts", "bootstrap.py");
            int code = await RunStreamingAsync(python, "\"" + script + "\" " + extraArgs, _repoRoot);
            _btnFix.Enabled = true;
            _btnCheck.Enabled = true;
            if (code == 0)
            {
                SetStatus("修复完成：环境就绪。", Color.FromArgb(120, 210, 150));
                _btnStart.Enabled = true;
            }
            else
            {
                SetStatus("修复没成功：日志里最后一屏就是原因，可复制出来发我。", Color.FromArgb(235, 120, 120));
            }
            if (thenCheck) { await CheckEnvironmentAsync(false); }
        }

        // ---------------- 服务进程 ----------------

        private static int FreePort(int preferred)
        {
            for (int candidate = preferred; candidate < preferred + 40; candidate++)
            {
                try
                {
                    TcpListener listener = new TcpListener(IPAddress.Loopback, candidate);
                    listener.Start();
                    listener.Stop();
                    return candidate;
                }
                catch (SocketException) { }
            }
            TcpListener any = new TcpListener(IPAddress.Loopback, 0);
            any.Start();
            int port = ((IPEndPoint)any.LocalEndpoint).Port;
            any.Stop();
            return port;
        }

        private async Task StartServerAsync()
        {
            if (_server != null && !_server.HasExited)
            {
                AppendLog("[i] 服务已经在跑，端口 " + _port);
                NavigateToConsole();
                return;
            }
            string python = File.Exists(VenvPython()) ? VenvPython() : PickPythonForBootstrap();
            if (python == null)
            {
                SetStatus("没有可用的 Python，先点「一键修复」。", Color.FromArgb(235, 120, 120));
                return;
            }
            _port = FreePort(PreferredPort);
            string config = Path.Combine(_packageDir, "configs", "system.yaml");
            string args = "-X utf8 -m spiritscout --config configs\\system.yaml --port " + _port;
            if (!File.Exists(config))
            {
                AppendLog("[!] 没找到 " + config + "：按 example 复制一份再启动");
            }

            ProcessStartInfo psi = BuildStartInfo(python, args);
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;
            psi.WorkingDirectory = _packageDir;
            psi.EnvironmentVariables["SPIRITSCOUT_SANDBOX_BACKEND"] = "host";
            psi.EnvironmentVariables["SPIRITSCOUT_EXECUTOR__SANDBOX_BACKEND"] = "host";
            psi.EnvironmentVariables["PYTHONUNBUFFERED"] = "1";

            Process proc = new Process();
            proc.StartInfo = psi;
            proc.OutputDataReceived += delegate(object s, DataReceivedEventArgs e)
            {
                if (e.Data != null) { AppendLog(e.Data); }
            };
            proc.ErrorDataReceived += delegate(object s, DataReceivedEventArgs e)
            {
                if (e.Data != null) { AppendLog(e.Data); }
            };
            try
            {
                proc.Start();
            }
            catch (Exception ex)
            {
                SetStatus("启动失败：" + ex.Message, Color.FromArgb(235, 120, 120));
                AppendLog("[x] 起不来：" + ex.Message);
                return;
            }
            proc.BeginOutputReadLine();
            proc.BeginErrorReadLine();
            _server = proc;
            _btnStop.Enabled = true;
            _btnStart.Enabled = false;
            SetStatus("正在启动控制台（端口 " + _port + "）…", Color.FromArgb(240, 190, 110));
            AppendLog("[>] python " + args);

            bool ready = await WaitForServerAsync(_port, 120000);
            if (ready)
            {
                SetStatus("控制台已在端口 " + _port + " 运行。", Color.FromArgb(120, 210, 150));
                _btnReload.Enabled = true;
                _btnExternal.Enabled = true;
                NavigateToConsole();
            }
            else
            {
                SetStatus("等了 120 秒控制台还没起来：看日志里最后几行报错。", Color.FromArgb(235, 120, 120));
                _btnStart.Enabled = true;
            }
        }

        private static async Task<bool> WaitForServerAsync(int port, int timeoutMs)
        {
            string url = "http://127.0.0.1:" + port + "/";
            int waited = 0;
            while (waited < timeoutMs)
            {
                if (await ProbeAsync(url)) { return true; }
                await Task.Delay(500);
                waited += 500;
            }
            return false;
        }

        private static async Task<bool> ProbeAsync(string url)
        {
            return await Task.Run(delegate
            {
                try
                {
                    HttpWebRequest request = (HttpWebRequest)WebRequest.Create(url);
                    request.Timeout = 2000;
                    request.Method = "GET";
                    request.Proxy = null;
                    using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
                    {
                        return (int)response.StatusCode >= 200 && (int)response.StatusCode < 500;
                    }
                }
                catch (Exception) { return false; }
            });
        }

        private void StopServer(bool userAsked)
        {
            Process proc = _server;
            _server = null;
            if (proc == null) { return; }
            try
            {
                if (!proc.HasExited)
                {
                    // 子进程树里可能有沙箱与工具子进程，按树杀，别留孤儿
                    ProcessStartInfo kill = new ProcessStartInfo("taskkill",
                        "/pid " + proc.Id + " /t /f");
                    kill.UseShellExecute = false;
                    kill.CreateNoWindow = true;
                    Process.Start(kill);
                    proc.WaitForExit(8000);
                }
            }
            catch (Exception ex) { AppendLog("[!] 停服务时出错：" + ex.Message); }
            _btnStop.Enabled = false;
            _btnStart.Enabled = true;
            _btnReload.Enabled = false;
            _btnExternal.Enabled = false;
            if (_web != null) { _web.Visible = false; }
            _placeholder.Visible = true;
            _placeholder.Text = "控制台已停止。";
            if (userAsked)
            {
                SetStatus("控制台已停止。", Color.FromArgb(200, 205, 215));
                AppendLog("[i] 已停止控制台");
            }
        }

        // ---------------- 内嵌浏览器 ----------------

        private async Task InitWebViewAsync()
        {
            if (_web == null)
            {
                _webReady = false;
                AppendLog("[!] 没有内嵌浏览器控件：" + (Runtime.LastError ?? "控件创建失败")
                          + "；退路是用「用浏览器打开」。");
                return;
            }
            try
            {
                // 用户数据目录指定到仓库外：默认会落在 exe 旁边（灵枢桌面版.exe.WebView2/），
                // 把工作区弄脏，只读安装目录下还会直接失败。
                CoreWebView2Environment environment =
                    await CoreWebView2Environment.CreateAsync(null, UserDataDir(), null);
                await _web.EnsureCoreWebView2Async(environment);
                _web.CoreWebView2.Settings.AreDevToolsEnabled = false;
                _web.CoreWebView2.Settings.IsStatusBarEnabled = false;
                _web.CoreWebView2.Settings.AreDefaultContextMenusEnabled = true;
                _webReady = true;
                AppendLog("[+] 内嵌浏览器就绪（WebView2 " + _web.CoreWebView2.Environment.BrowserVersionString + "）");
                _web.NavigationCompleted += delegate(object sender, CoreWebView2NavigationCompletedEventArgs e)
                {
                    if (e.IsSuccess)
                    {
                        string title = "";
                        try { title = _web.CoreWebView2.DocumentTitle; } catch (Exception) { }
                        AppendLog("[+] 页面已加载：" + (title.Length > 0 ? title : "（无标题）"));
                    }
                    else
                    {
                        AppendLog("[!] 页面加载失败：" + e.WebErrorStatus);
                    }
                };
            }
            catch (Exception ex)
            {
                _webReady = false;
                AppendLog("[!] 内嵌浏览器初始化失败：" + ex.Message);
                AppendLog("    退路：仍然可以用「用浏览器打开」在 Edge 的独立窗口里看控制台。");
            }
        }

        /// <summary>WebView2 的用户数据目录：跟解压目录一样三级回退，别写进工作区。</summary>
        private string UserDataDir()
        {
            string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            if (!string.IsNullOrEmpty(localAppData))
            {
                string preferred = Path.Combine(localAppData, "SpiritScout", "webview2");
                try
                {
                    Directory.CreateDirectory(preferred);
                    return preferred;
                }
                catch (Exception) { }
            }
            string beside = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "灵枢桌面版-lib", "webview2");
            try
            {
                Directory.CreateDirectory(beside);
                return beside;
            }
            catch (Exception) { }
            string temp = Path.Combine(Path.GetTempPath(), "SpiritScout-webview2");
            Directory.CreateDirectory(temp);
            return temp;
        }
        private void NavigateToConsole()
        {
            string url = "http://127.0.0.1:" + _port + "/";
            if (_webReady)
            {
                _placeholder.Visible = false;
                _web.Visible = true;
                _web.Source = new Uri(url);
                AppendLog("[>] 打开 " + url);
            }
            else
            {
                OpenExternal();
            }
        }

        private void ReloadPage()
        {
            if (_webReady && _web.CoreWebView2 != null) { _web.CoreWebView2.Reload(); }
        }

        private void OpenExternal()
        {
            string url = "http://127.0.0.1:" + _port + "/";
            try
            {
                // Edge 的 --app 模式：独立窗口、没有地址栏与标签页，最接近「软件」的样子
                string edge = FindEdge();
                if (edge != null)
                {
                    Process.Start(new ProcessStartInfo(edge, "--app=" + url) { UseShellExecute = false });
                }
                else
                {
                    Process.Start(url);
                }
            }
            catch (Exception ex) { AppendLog("[x] 打不开浏览器：" + ex.Message); }
        }

        private static string FindEdge()
        {
            string[] candidates = new string[]
            {
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), "Microsoft", "Edge", "Application", "msedge.exe"),
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Microsoft", "Edge", "Application", "msedge.exe"),
            };
            foreach (string path in candidates)
            {
                if (File.Exists(path)) { return path; }
            }
            return null;
        }

        // ---------------- 管理员密码 ----------------

        private void SetPassword()
        {
            string python = File.Exists(VenvPython()) ? VenvPython() : PickPythonForBootstrap();
            if (python == null)
            {
                AppendLog("[x] 没有可用的 Python，设不了密码。");
                return;
            }
            try
            {
                // 交互式命令（要输两遍密码），必须给它一个真窗口
                ProcessStartInfo psi = new ProcessStartInfo("cmd.exe",
                    "/k \"" + python + "\" -X utf8 -m spiritscout --set-admin-password");
                psi.WorkingDirectory = _packageDir;
                psi.UseShellExecute = true;
                Process.Start(psi);
                AppendLog("[>] 已开一个窗口让你设管理员密码（输两遍，不回显）。");
            }
            catch (Exception ex) { AppendLog("[x] 起不来密码窗口：" + ex.Message); }
        }

        // ---------------- 收尾 ----------------

        private void OnClosing(object sender, FormClosingEventArgs e)
        {
            _closing = true;
            StopServer(false);
        }
    }
}
