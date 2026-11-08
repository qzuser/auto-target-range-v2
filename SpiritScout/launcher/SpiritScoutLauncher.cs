// 灵枢 Web 控制台 —— Windows 签名启动器（替代 .cmd 的可签名入口）
//
// 为什么需要它：.cmd / .bat 没有 Authenticode 容器，Windows 的信任提供程序
// 直接拒绝（Set-AuthenticodeSignature 会报 "The form specified for the subject
// is not one supported or known by the specified trust provider"）。想让双击入口
// 显示发布者、不再报"未知发布者"，入口必须是 PE 文件。这个 exe 复刻
// 启动服务.cmd 的全部行为，编译后由 launcher/build-launcher.ps1 签名。
//
// 行为与 .cmd 保持一致：
//   1. 代码页切成 UTF-8，窗口标题固定，工作目录切到 exe 所在目录；
//   2. 没设模型 key 时给一段可照做的提示（不阻断启动）；
//   3. 前台调用 start-local.ps1，不重定向输出，报错留在窗口里；
//   4. 退出后停住，等按键再关窗。
using System;
using System.Diagnostics;
using System.IO;
using System.Text;

namespace SpiritScoutLauncher
{
    internal static class Program
    {
        /// <summary>控制台端口；与 启动服务.cmd 里写死的一致。</summary>
        private const int Port = 8010;

        private static int Main()
        {
            // 与 chcp 65001 等价：不写 BOM，避免首行被当成内容回显
            Console.OutputEncoding = new UTF8Encoding(false);
            Console.Title = "SpiritScout 灵枢 - 前台服务（关闭本窗口即全部停止）";

            string root = Path.GetDirectoryName(Process.GetCurrentProcess().MainModule.FileName);
            if (string.IsNullOrEmpty(root))
            {
                root = Directory.GetCurrentDirectory();
            }
            Directory.SetCurrentDirectory(root);

            if (Environment.GetEnvironmentVariable("SPIRITSCOUT_REMOTE_LLM_KEY") == null)
            {
                Console.WriteLine("[i] 这次没检测到模型 key（SPIRITSCOUT_REMOTE_LLM_KEY）。");
                Console.WriteLine("    不影响启动：进控制台后到「模型」页给供应商填 key 就行，");
                Console.WriteLine("    密钥加密存进本机密钥库，以后不用再设环境变量。");
                Console.WriteLine("    想用环境变量也可以：setx SPIRITSCOUT_REMOTE_LLM_KEY \"你的key\"");
                Console.WriteLine();
            }

            string script = Path.Combine(root, "start-local.ps1");
            if (!File.Exists(script))
            {
                Console.WriteLine("[x] 找不到 start-local.ps1：" + script);
                Console.WriteLine("    这个 exe 必须和 start-local.ps1 放在同一个目录。");
                return Pause(1);
            }

            var start = new ProcessStartInfo("powershell")
            {
                Arguments = "-NoProfile -ExecutionPolicy Bypass -File \"" + script + "\" -Port " + Port,
                UseShellExecute = false,
                WorkingDirectory = root,
            };

            int code;
            try
            {
                using (Process child = Process.Start(start))
                {
                    // 前台等待：Ctrl+C 会同时传到子进程，和直接在 cmd 里跑一样
                    child.WaitForExit();
                    code = child.ExitCode;
                }
            }
            catch (Exception exc)
            {
                Console.WriteLine("[x] 启动失败：" + exc.Message);
                code = 1;
            }

            Console.WriteLine();
            Console.WriteLine("[=] 控制台已退出。");
            Console.WriteLine("    若上面报错，直接看本窗口的输出（控制台为前台运行，不重定向到日志文件）。");
            return Pause(code);
        }

        /// <summary>等价于 .cmd 结尾的 pause：窗口留住，报错看得见。</summary>
        private static int Pause(int code)
        {
            Console.WriteLine();
            Console.WriteLine("按任意键关闭窗口…");
            try
            {
                Console.ReadKey(true);
            }
            catch (InvalidOperationException)
            {
                // 没有可交互的控制台（被重定向时）就直接返回，不卡住调用方
            }
            return code;
        }
    }
}
