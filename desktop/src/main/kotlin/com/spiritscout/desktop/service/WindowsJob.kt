package com.spiritscout.desktop.service

import com.sun.jna.Library
import com.sun.jna.Memory
import com.sun.jna.Native
import com.sun.jna.Pointer
import com.sun.jna.platform.win32.WinNT

/**
 * Windows Job Object with KILL_ON_JOB_CLOSE.
 *
 * The desktop JVM keeps the only job handle. If the JVM exits normally,
 * crashes, or is terminated, Windows closes the handle and kills the backend
 * process tree without relying on JVM-side shutdown code.
 */
class WindowsJob private constructor(
    private val kernel32: JobKernel32,
    private val handle: WinNT.HANDLE
) : AutoCloseable {
    override fun close() {
        if (Pointer.nativeValue(handle.pointer) != 0L) {
            kernel32.CloseHandle(handle)
        }
    }

    companion object {
        private const val JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
        private const val JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
        private const val PROCESS_SET_QUOTA = 0x0100
        private const val PROCESS_TERMINATE = 0x0001
        private const val EXTENDED_LIMIT_INFORMATION_BYTES = 144
        private const val LIMIT_FLAGS_OFFSET = 16

        fun attach(processId: Long): Result<WindowsJob> = runCatching {
            require(processId in 1..Int.MAX_VALUE) { "无效的后端进程 ID：$processId" }
            val kernel32 = Native.load("kernel32", JobKernel32::class.java)
            val job = kernel32.CreateJobObjectW(null, null)
                ?: error("CreateJobObjectW 返回空句柄")
            if (Pointer.nativeValue(job.pointer) == 0L) {
                error("CreateJobObjectW 返回空句柄")
            }
            val process = kernel32.OpenProcess(
                PROCESS_SET_QUOTA or PROCESS_TERMINATE,
                false,
                processId.toInt()
            )
            if (process == null || Pointer.nativeValue(process.pointer) == 0L) {
                kernel32.CloseHandle(job)
                error("无法打开后端进程 $processId")
            }
            try {
                val limits = Memory(EXTENDED_LIMIT_INFORMATION_BYTES.toLong())
                limits.clear()
                limits.setInt(LIMIT_FLAGS_OFFSET.toLong(), JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
                if (!kernel32.SetInformationJobObject(
                        job,
                        JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                        limits,
                        EXTENDED_LIMIT_INFORMATION_BYTES
                    )
                ) {
                    error("SetInformationJobObject 失败：${Native.getLastError()}")
                }
                if (!kernel32.AssignProcessToJobObject(job, process)) {
                    error("AssignProcessToJobObject 失败：${Native.getLastError()}")
                }
                WindowsJob(kernel32, job)
            } catch (error: Throwable) {
                kernel32.CloseHandle(process)
                kernel32.CloseHandle(job)
                throw error
            } finally {
                kernel32.CloseHandle(process)
            }
        }
    }
}

private interface JobKernel32 : Library {
    fun CreateJobObjectW(attributes: Pointer?, name: String?): WinNT.HANDLE?
    fun SetInformationJobObject(
        job: WinNT.HANDLE,
        informationClass: Int,
        information: Pointer,
        informationLength: Int
    ): Boolean

    fun AssignProcessToJobObject(job: WinNT.HANDLE, process: WinNT.HANDLE): Boolean
    fun OpenProcess(access: Int, inherit: Boolean, processId: Int): WinNT.HANDLE?
    fun CloseHandle(handle: WinNT.HANDLE): Boolean
}
