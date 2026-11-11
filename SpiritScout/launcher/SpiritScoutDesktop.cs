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
using System.Security.Cryptography;
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

    /// <summary>
    /// 单文件版：exe 末尾挂着一个 zip（里面是 py\ 与 configs\），尾部 24 字节是
    /// [载荷长度][保留][标记]。首次启动把载荷倒出来解到可写目录，之后直接用。
    /// 这样发出去就是「一个 exe，双击能跑」，不用带一堆文件、也不用机器上装 Python。
    /// </summary>
    internal static class BundledRuntime
    {
        private const string Marker = "SSRTPAY1";    // 尾部最后 8 字节；改了就互不认
        // 解出来的树得能自证完整：清单是 大小<TAB>相对路径，按行读，不引 JSON 库
        private const string ManifestName = "runtime.manifest.tsv";
        private const string ReadyMarker = ".ready";
        internal const string UserDataFolder = ".spiritscout";
        private const int TrailerSize = 40;          // 8 长度 + 24 校验 + 8 标记
        private const int HashBytes = 24;            // 载荷 SHA-256 只存前 24 字节，够防下载残缺

        internal static string Root { get; private set; }
        internal static string Error { get; private set; }

        /// <summary>当前这个 exe 是不是带载荷的单文件版。</summary>
        internal static bool HasPayload()
        {
            long offset;
            long length;
            try { return ReadTrailer(Application.ExecutablePath, out offset, out length); }
            catch (Exception) { return false; }
        }

        private static bool ReadTrailer(string self, out long offset, out long length)
        {
            offset = 0;
            length = 0;
            using (FileStream fs = File.OpenRead(self))
            {
                if (fs.Length < TrailerSize + 1024) { return false; }
                fs.Seek(-TrailerSize, SeekOrigin.End);
                byte[] tail = new byte[TrailerSize];
                if (fs.Read(tail, 0, TrailerSize) != TrailerSize) { return false; }
                string marker = Encoding.ASCII.GetString(tail, 32, 8);
                if (marker != Marker) { return false; }
                length = BitConverter.ToInt64(tail, 0);
                offset = fs.Length - TrailerSize - length;
                return length > 0 && offset > 0;
            }
        }

        /// <summary>尾标里记的载荷 SHA-256 前 24 字节；读不到就返回空。</summary>
        private static byte[] ReadExpectedHash(string self)
        {
            using (FileStream fs = File.OpenRead(self))
            {
                if (fs.Length < TrailerSize) { return new byte[0]; }
                fs.Seek(-TrailerSize, SeekOrigin.End);
                byte[] tail = new byte[TrailerSize];
                if (fs.Read(tail, 0, TrailerSize) != TrailerSize) { return new byte[0]; }
                byte[] hash = new byte[HashBytes];
                Array.Copy(tail, 8, hash, 0, HashBytes);
                return hash;
            }
        }

        /// <summary>倒出来的载荷够不够完整？下载断了/被截断的 exe 会在这里露馅。</summary>
        private static bool VerifyPayload(string zip, byte[] expected)
        {
            if (expected == null || expected.Length != HashBytes) { return true; }
            using (FileStream fs = File.OpenRead(zip))
            using (SHA256 sha = SHA256.Create())
            {
                byte[] actual = sha.ComputeHash(fs);
                for (int i = 0; i < HashBytes; i++)
                {
                    if (actual[i] != expected[i]) { return false; }
                }
            }
            return true;
        }

        /// <summary>
        /// 运行时能不能用。光看 .ready 不够：本机实测过杀毒/EDR 把安装目录里某些
        /// 文件单独清理掉，.ready 还在、python 还在，但缺一个知识库模块就让首页 500，
        /// 所以这里额外抽查几个关键文件。
        /// <para>requireMarker=false 用在**刚解压完、标记还没写**的那一刻——
        /// 否则会因为「没有 .ready」判定失败，白解三次。</para>
        /// </summary>
        private static bool Ready(string dir, bool requireMarker)
        {
            if (!File.Exists(Path.Combine(dir, "py", "python.exe"))) { return false; }
            if (!File.Exists(Path.Combine(dir, "configs", "system.yaml"))) { return false; }
            if (requireMarker && !File.Exists(Path.Combine(dir, ReadyMarker))) { return false; }
            string site = Path.Combine(dir, "py", "Lib", "site-packages");
            string[] sentinels = new string[]
            {
                Path.Combine(site, "spiritscout", "web", "app.py"),
                Path.Combine(site, "spiritscout", "knowledge", "seed.py"),
                Path.Combine(site, "spiritscout", "knowledge", "data", "seed.json"),
                Path.Combine(site, "litellm", "__init__.py"),
            };
            foreach (string path in sentinels)
            {
                if (!File.Exists(path)) { return false; }
            }
            return true;
        }

        /// <summary>按清单核对解出来的树：缺文件或大小不符都算坏。返回问题描述（最多几条）。</summary>
        private static string VerifyTree(string dir, out int broken)
        {
            broken = 0;
            string manifest = Path.Combine(dir, ManifestName);
            if (!File.Exists(manifest)) { return ""; }   // 老载荷没有清单，别误判成坏
            string[] lines;
            try { lines = File.ReadAllLines(manifest); }
            catch (IOException) { return ""; }
            List<string> problems = new List<string>();
            foreach (string raw in lines)
            {
                string line = raw.Trim();
                if (line.Length == 0 || line[0] == '#') { continue; }
                int tab = line.IndexOf('\t');
                if (tab <= 0) { continue; }
                long size;
                if (!long.TryParse(line.Substring(0, tab), out size)) { continue; }
                string rel = line.Substring(tab + 1).Replace('/', Path.DirectorySeparatorChar);
                string full = Path.Combine(dir, rel);
                FileInfo info = new FileInfo(full);
                if (!info.Exists || info.Length != size)
                {
                    broken++;
                    if (problems.Count < 5) { problems.Add(rel.Replace(Path.DirectorySeparatorChar, '/')); }
                }
            }
            if (broken == 0) { return ""; }
            return string.Join("、", problems.ToArray()) + (broken > problems.Count ? " 等 " + broken + " 个" : "");
        }

        /// <summary>解出运行时并返回程序目录；失败返回 null，原因写进 Error。</summary>
        internal static string Ensure(Action<string> progress)
        {
            Error = null;
            string self = Application.ExecutablePath;
            long offset;
            long length;
            if (!ReadTrailer(self, out offset, out length))
            {
                Error = "exe 尾部没有运行时载荷";
                return null;
            }
            string tag = length.ToString() + "-" + Fingerprint(self, offset).ToString("x8");

            List<string> probes = new List<string>();
            string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            if (!string.IsNullOrEmpty(localAppData))
            {
                probes.Add(Path.Combine(localAppData, "SpiritScout", "runtime", tag));
            }
            string exeDir = Path.GetDirectoryName(self);
            if (!string.IsNullOrEmpty(exeDir))
            {
                probes.Add(Path.Combine(exeDir, "灵枢运行时-" + tag));
            }
            probes.Add(Path.Combine(Path.GetTempPath(), "SpiritScout-runtime", tag));

            // 已经解过一次就别再动：同一台机器第二次启动直接进界面。
            // 但 .ready 在、关键文件却缺（杀软清理过）时要认账，清掉重解。
            foreach (string candidate in probes)
            {
                if (Ready(candidate, true)) { Root = candidate; return candidate; }
                if (File.Exists(Path.Combine(candidate, ReadyMarker)))
                {
                    progress("上次解出来的运行时缺文件，重解一遍：" + candidate);
                    try { Directory.Delete(candidate, true); } catch (Exception) { }
                }
            }

            List<string> errors = new List<string>();
            foreach (string candidate in probes)
            {
                try
                {
                    Directory.CreateDirectory(candidate);
                    progress("解出运行时到：" + candidate);
                    string zip = Path.Combine(candidate, "runtime.zip");
                    ExtractPayload(self, offset, length, zip, progress);
                    if (!VerifyPayload(zip, ReadExpectedHash(self)))
                    {
                        throw new InvalidOperationException("载荷校验不通过（下载不完整或被改过）");
                    }
                    progress("展开 " + (length / 1048576) + " MB，两万多个文件，耐心等一下…");
                    Expand(zip, candidate);
                    try { File.Delete(zip); } catch (IOException) { }
                    if (!File.Exists(Path.Combine(candidate, "py", "python.exe")))
                    {
                        throw new InvalidOperationException("解开后没有 py\\python.exe");
                    }
                    int broken;
                    string problems = VerifyTree(candidate, out broken);
                    if (broken > 0)
                    {
                        throw new InvalidOperationException(
                            "解开后缺 " + broken + " 个文件（可能被杀毒软件清理）：" + problems);
                    }
                    if (!Ready(candidate, false))
                    {
                        throw new InvalidOperationException("解出来的运行时没通过自检");
                    }
                    AdoptUserData(candidate, progress);
                    File.WriteAllText(Path.Combine(candidate, ReadyMarker), tag, Encoding.UTF8);
                    Root = candidate;
                    return candidate;
                }
                catch (Exception ex)
                {
                    errors.Add(candidate + " → " + ex.Message);
                    try { Directory.Delete(candidate, true); } catch (Exception) { }
                }
            }
            Error = string.Join("；", errors.ToArray());
            return null;
        }

        /// <summary>
        /// 换了新版本的单文件 exe，运行时会解到新目录（目录名带载荷指纹），而模型密钥、
        /// 会话、知识库都在上一份运行时的 .spiritscout 里。不搬的话，用户升个版本就发现
        /// 「密钥没了、历史也没了」，看起来就像环境配置出错。这里把同目录下最新的那份
        /// .spiritscout 复制过来（新目录里还没有数据时才做）。
        /// </summary>
        internal static void AdoptUserData(string target, Action<string> progress)
        {
            string mine = Path.Combine(target, UserDataFolder);
            if (Directory.Exists(mine) && Directory.GetFileSystemEntries(mine).Length > 0) { return; }
            string parent = Path.GetDirectoryName(target.TrimEnd(Path.DirectorySeparatorChar));
            if (string.IsNullOrEmpty(parent) || !Directory.Exists(parent)) { return; }

            string best = null;
            DateTime newest = DateTime.MinValue;
            foreach (string sibling in Directory.GetDirectories(parent))
            {
                if (string.Equals(Path.GetFullPath(sibling).TrimEnd(Path.DirectorySeparatorChar),
                                  Path.GetFullPath(target).TrimEnd(Path.DirectorySeparatorChar),
                                  StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }
                string data = Path.Combine(sibling, UserDataFolder);
                if (!Directory.Exists(data) || Directory.GetFileSystemEntries(data).Length == 0) { continue; }
                DateTime stamp = Directory.GetLastWriteTimeUtc(data);
                if (stamp > newest) { newest = stamp; best = data; }
            }
            if (best == null) { return; }

            try
            {
                CopyTree(best, mine);
                if (progress != null) { progress("[+] 已把上一次的配置与数据带过来：" + best); }
            }
            catch (IOException ex)
            {
                if (progress != null) { progress("[!] 旧数据没搬全（可以手动拷 " + best + "）：" + ex.Message); }
            }
            catch (UnauthorizedAccessException ex)
            {
                if (progress != null) { progress("[!] 旧数据没搬全（权限不够）：" + ex.Message); }
            }
        }

        private static void CopyTree(string from, string to)
        {
            Directory.CreateDirectory(to);
            foreach (string file in Directory.GetFiles(from))
            {
                File.Copy(file, Path.Combine(to, Path.GetFileName(file)), true);
            }
            foreach (string dir in Directory.GetDirectories(from))
            {
                CopyTree(dir, Path.Combine(to, Path.GetFileName(dir)));
            }
        }

        /// <summary>载荷前 64 KB 的 FNV-1a：同一份运行时算出来的值一致，攒成缓存目录名。</summary>
        private static uint Fingerprint(string self, long offset)
        {
            uint hash = 2166136261;
            using (FileStream fs = File.OpenRead(self))
            {
                fs.Seek(offset, SeekOrigin.Begin);
                byte[] buffer = new byte[65536];
                int read = fs.Read(buffer, 0, buffer.Length);
                for (int i = 0; i < read; i++)
                {
                    hash = (hash ^ buffer[i]) * 16777619;
                }
            }
            return hash;
        }

        private static void ExtractPayload(string self, long offset, long length, string target, Action<string> progress)
        {
            using (FileStream input = File.OpenRead(self))
            using (FileStream output = File.Create(target))
            {
                input.Seek(offset, SeekOrigin.Begin);
                byte[] buffer = new byte[1 << 20];
                long left = length;
                long done = 0;
                while (left > 0)
                {
                    int want = (int)Math.Min(buffer.Length, left);
                    int read = input.Read(buffer, 0, want);
                    if (read <= 0) { throw new IOException("载荷读取提前结束"); }
                    output.Write(buffer, 0, read);
                    left -= read;
                    done += read;
                    if (progress != null && done % (64L << 20) < buffer.Length)
                    {
                        progress("已倒出 " + (done / 1048576) + " / " + (length / 1048576) + " MB");
                    }
                }
            }
        }

        /// <summary>解 zip：优先系统自带的 tar.exe（快），没有就退到 PowerShell 的 Expand-Archive。</summary>
        private static void Expand(string zip, string dir)
        {
            string tar = Path.Combine(Environment.SystemDirectory, "tar.exe");
            if (File.Exists(tar))
            {
                ProcessStartInfo psi = new ProcessStartInfo(tar, "-xf \"" + zip + "\" -C \"" + dir + "\"");
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                using (Process p = Process.Start(psi))
                {
                    p.WaitForExit();
                    if (p.ExitCode == 0) { return; }
                }
            }
            ProcessStartInfo ps = new ProcessStartInfo("powershell.exe",
                "-NoProfile -ExecutionPolicy Bypass -Command \"Expand-Archive -LiteralPath '" + zip
                + "' -DestinationPath '" + dir + "' -Force\"");
            ps.UseShellExecute = false;
            ps.CreateNoWindow = true;
            using (Process p = Process.Start(ps))
            {
                p.WaitForExit();
                if (p.ExitCode != 0) { throw new InvalidOperationException("解题失败（tar 与 Expand-Archive 都没成）"); }
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

        // 不是 readonly：单文件版要先开窗、再解运行时，解完才知道真正的程序目录
        private string _repoRoot;      // 仓库根（start-local.ps1 所在目录）；便携/单文件版是程序目录
        private string _packageDir;    // SpiritScout/（pyproject.toml 与 .venv 在这）；便携/单文件版是程序目录
        private string _logDir;
        private string _pythonOverride; // desktop.json 里指定的解释器（便携/单文件版内嵌的那个）
        private bool _portable;         // 便携版：依赖已装进内嵌 Python，没有 venv 也没有 bootstrap.py
        private bool _singleFile;       // 单文件版：exe 尾巴上挂着运行时 zip，首次启动解出来
        private bool _runtimeBroken;    // 单文件版这次没解开运行时（杀软拦、磁盘满、目录不可写）

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
            // 三种形态，优先级从高到低：
            //   1. 单文件版：exe 尾部挂着运行时 zip（build-single.ps1 拼的），先开窗再解；
            //   2. 便携版：exe 旁边的 desktop.json 指路（root=程序目录、python=内嵌解释器）；
            //   3. 仓库版：在仓库根里找 SpiritScout/。
            _singleFile = BundledRuntime.HasPayload();
            DesktopConfig cfg = ReadDesktopConfig();
            if (_singleFile)
            {
                // 真正的程序目录要等运行时解完才知道：先拿 exe 所在目录顶着，日志也先写这儿
                _repoRoot = Path.GetDirectoryName(Application.ExecutablePath);
                _packageDir = _repoRoot;
                _pythonOverride = null;
                _portable = true;
            }
            else if (cfg != null && !string.IsNullOrEmpty(cfg.Root) && Directory.Exists(cfg.Root))
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

            ApplyAppIcon();
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

        /// <summary>
        /// 窗口和任务栏的图标。WinForms 不会自动用 exe 里那份——不设 Icon 的话标题栏
        /// 和任务栏一直是 .NET 那个通用图标，看着就像「图标根本没改」。
        /// 优先读构建时嵌进来的 app.icon（和网页 favicon 同一张图），
        /// 拿不到再从 exe 资源里抽。
        /// </summary>
        private void ApplyAppIcon()
        {
            try
            {
                System.IO.Stream stream =
                    typeof(DesktopForm).Assembly.GetManifestResourceStream("app.icon");
                if (stream != null)
                {
                    using (stream)
                    {
                        Icon = new Icon(stream);
                        return;
                    }
                }
            }
            catch (Exception) { }
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); }
            catch (Exception) { }
        }
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
            AppendLog("灵枢桌面版启动。程序目录：" + _repoRoot
                + (_singleFile ? "（单文件版：运行时随 exe 一起）" : ""));
            try
            {
                if (_singleFile) { await UnpackBundledRuntimeAsync(); }
                await InitWebViewAsync();
                await CheckEnvironmentAsync(false);
            }
            catch (Exception ex)
            {
                AppendLog("[x] 启动自检出错：" + ex.Message);
                SetStatus("启动自检出错：日志里有细节。", Color.FromArgb(235, 120, 120));
            }
        }

        /// <summary>单文件版第一次启动：把 exe 尾部的 zip 解出来，之后启动直接复用。</summary>
        private async Task UnpackBundledRuntimeAsync()
        {
            SetStatus("正在准备运行时（首次启动要解一次，约 320 MB）…", Color.FromArgb(240, 190, 110));
            _btnCheck.Enabled = false;
            _btnFix.Enabled = false;
            _btnStart.Enabled = false;
            string root = await Task.Run(delegate
            {
                return BundledRuntime.Ensure(delegate(string message) { AppendLog(message); });
            });
            _btnCheck.Enabled = true;
            _btnFix.Enabled = true;
            if (string.IsNullOrEmpty(root))
            {
                // 关键：这里不能把 _singleFile 关掉。关掉之后就按「便携版 + desktop.json」
                // 继续走，最后弹出一句「desktop.json 指向的解释器不存在」——用户根本
                // 不知道发生了什么，还以为单文件版要装环境。
                _runtimeBroken = true;
                AppendLog("[x] 内置运行时解不出来：" + BundledRuntime.Error);
                SetStatus("内置运行时没解开：点「重试解压」；还不行就看日志里的原因。", Color.FromArgb(235, 120, 120));
                _btnStart.Enabled = false;
                _btnFix.Text = "重试解压";
                _btnFix.Enabled = true;
                _placeholder.Text = "单文件版自带运行时，不需要装 Python。\n"
                    + "这次没解开，多半是杀毒软件拦了、磁盘空间不够，或者当前目录不能写。";
                return;
            }
            _repoRoot = root;
            _packageDir = root;
            _pythonOverride = Path.Combine(root, "py", "python.exe");
            _portable = true;
            _logDir = Path.Combine(root, LogFolderName);
            _runtimeBroken = false;
            _btnFix.Text = "一键修复";
            AppendLog("[+] 运行时就绪：" + root);
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
            // 宿主机要是设过 PYTHONHOME / PYTHONPATH / PYTHONSTARTUP，内嵌解释器会被带歪
            // （典型症状：同一个 exe 在别人机器上 import 就崩）。这里一律清掉。
            psi.EnvironmentVariables.Remove("PYTHONHOME");
            psi.EnvironmentVariables.Remove("PYTHONPATH");
            psi.EnvironmentVariables.Remove("PYTHONSTARTUP");
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
            if (_runtimeBroken)
            {
                // 运行时都没解出来，再去探解释器只会弹一句看不懂的 desktop.json 报错
                SetStatus("内置运行时还没准备好：点「重试解压」。", Color.FromArgb(240, 190, 110));
                _btnStart.Enabled = false;
                return;
            }
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
                SetStatus("这个 exe 只是窗口壳，需要同目录的运行时；想双击就用请下「单文件版」。", Color.FromArgb(235, 120, 120));
                AppendLog("[x] 找不到内置 Python：" + (string.IsNullOrEmpty(python) ? "（没配解释器）" : python));
                AppendLog("    这个 exe 是 834 KB 的窗口壳，运行时（py\\ + configs\\）得跟它放在一起；"
                    + "嫌配环境麻烦就下 spiritscout-<版本>-single-win64.exe，那个一个文件全带。");
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
                if (_runtimeBroken && _singleFile)
                {
                    AppendLog("[>] 重新解一次内置运行时");
                    await UnpackBundledRuntimeAsync();
                    await CheckEnvironmentAsync(false);
                    return;
                }
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
                AppendLog("[!] 没有内嵌浏览器控件：" + (Runtime.LastError ?? "控件创建失败"));
                AppendLog("    Windows 10/11 一般自带 WebView2 运行时；缺了就去装一个名字叫"
                    + "「Microsoft Edge WebView2 Runtime」的组件，装完重开本程序。");
                SetStatus("缺内嵌浏览器组件：点「用浏览器打开」照样能用。", Color.FromArgb(240, 190, 110));
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
