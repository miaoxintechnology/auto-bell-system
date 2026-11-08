using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Windows.Forms;

[assembly: AssemblyTitle("自动铃声系统安装程序")]
[assembly: AssemblyDescription("自动铃声系统安装引导")]
[assembly: AssemblyProduct("自动铃声系统")]
[assembly: AssemblyCompany("AutoBell")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

internal static class SetupBootstrapper
{
    [STAThread]
    private static void Main(string[] args)
    {
        string cache = FindWritableCache();
        if (cache == null)
        {
            MessageBox.Show(
                "安装程序无法创建临时目录，请把安装包复制到桌面或 D 盘后重试。",
                "自动铃声系统",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            return;
        }

        string temp = Path.Combine(cache, "temp");
        string setup = Path.Combine(cache, "AutoBellSystem-Setup-Inner.exe");
        try
        {
            Directory.CreateDirectory(temp);
            ExtractEmbeddedInstaller(setup);

            var startInfo = new ProcessStartInfo
            {
                FileName = setup,
                Arguments = JoinArguments(args),
                WorkingDirectory = cache,
                UseShellExecute = false,
            };
            // 覆盖用户机器上有问题的 %TEMP%，让 Inno Setup 使用可写目录。
            startInfo.EnvironmentVariables["TEMP"] = temp;
            startInfo.EnvironmentVariables["TMP"] = temp;

            Process process = Process.Start(startInfo);
            if (process == null)
            {
                throw new InvalidOperationException("无法启动安装程序");
            }
            process.WaitForExit();
            if (process.ExitCode != 0)
            {
                MessageBox.Show(
                    "安装程序返回代码：" + process.ExitCode + "\n如果安装已取消，可以忽略此提示。",
                    "自动铃声系统",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Information);
            }
        }
        catch (Exception error)
        {
            MessageBox.Show(
                "无法启动安装程序：\n" + error.Message,
                "自动铃声系统",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
        }
        finally
        {
            try
            {
                if (File.Exists(setup)) File.Delete(setup);
                if (Directory.Exists(temp)) Directory.Delete(temp, true);
                if (Directory.Exists(cache) && Directory.GetFileSystemEntries(cache).Length == 0)
                {
                    Directory.Delete(cache, true);
                }
            }
            catch
            {
                // 安装程序可能仍占用文件，留待下次清理
            }
        }
    }

    private static string FindWritableCache()
    {
        var candidates = new[]
        {
            Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "AutoBellSetupCache"),
            Path.Combine(
                Path.GetDirectoryName(Application.ExecutablePath) ?? ".",
                "AutoBellSetupCache"),
            Path.Combine(Path.GetTempPath(), "AutoBellSetupCache"),
        };
        foreach (string candidate in candidates)
        {
            try
            {
                Directory.CreateDirectory(candidate);
                string probe = Path.Combine(candidate, ".probe");
                File.WriteAllText(probe, "ok");
                File.Delete(probe);
                return candidate;
            }
            catch
            {
                // 尝试下一个目录
            }
        }
        return null;
    }

    private static void ExtractEmbeddedInstaller(string target)
    {
        using (Stream stream = Assembly.GetExecutingAssembly()
            .GetManifestResourceStream("AutoBellSetup.exe"))
        {
            if (stream == null)
            {
                throw new InvalidOperationException("安装程序资源缺失");
            }
            using (FileStream output = File.Create(target))
            {
                stream.CopyTo(output);
            }
        }
    }

    private static string JoinArguments(string[] args)
    {
        var builder = new StringBuilder();
        foreach (string argument in args)
        {
            if (builder.Length > 0) builder.Append(' ');
            if (argument.Contains(" ") || argument.Contains("\t"))
            {
                builder.Append('"').Append(argument.Replace("\"", "\\\"")).Append('"');
            }
            else
            {
                builder.Append(argument);
            }
        }
        return builder.ToString();
    }
}
