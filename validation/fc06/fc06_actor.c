/* Inert Linux-only process fixture. No chemistry, network or scheduler calls. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

static long long now_ms(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) _exit(110);
    return (long long)t.tv_sec * 1000 + t.tv_nsec / 1000000;
}
static void pause_ms(void) {
    struct timespec t = {0, 10000000};
    while (nanosleep(&t, &t) && errno == EINTR) {}
}
static void event(const char *directory, const char *name, pid_t wrapper) {
    char path[4096], body[512];
    int length = snprintf(path, sizeof(path), "%s/%s.json", directory, name);
    if (length < 0 || length >= (int)sizeof(path)) _exit(111);
    int fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
    if (fd < 0) _exit(112);
    length = snprintf(body, sizeof(body),
        "{\"pid\":%ld,\"ppid\":%ld,\"wrapper_pid\":%ld,\"monotonic_ms\":%lld}\n",
        (long)getpid(), (long)getppid(), (long)wrapper, now_ms());
    if (length <= 0 || write(fd, body, (size_t)length) != length || fsync(fd)) _exit(113);
    if (close(fd)) _exit(114);
}
static int present(const char *directory, const char *name) {
    char path[4096];
    int n = snprintf(path, sizeof(path), "%s/%s", directory, name);
    if (n < 0 || n >= (int)sizeof(path)) _exit(115);
    return access(path, F_OK) == 0;
}
static void deny_subreaper(void) {
    /* This process only: force the real PR_SET_CHILD_SUBREAPER syscall to EPERM. */
    struct sock_filter instructions[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_prctl, 0, 3),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[0])),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, PR_SET_CHILD_SUBREAPER, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
    };
    struct sock_fprog filter = {(unsigned short)(sizeof(instructions) / sizeof(instructions[0])), instructions};
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) || prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &filter)) _exit(116);
    errno = 0;
    if (prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != -1 || errno != EPERM) _exit(117);
    if (dprintf(2, "FC06_REAL_PRCTL_DENIED errno=%d\n", errno) < 0) _exit(118);
}
int main(int argc, char **argv) {
    if (argc >= 3 && strcmp(argv[1], "--deny-prctl") == 0) {
        deny_subreaper();
        execv(argv[2], argv + 2);
        return 119;
    }
    if (argc != 6) return 120;
    const char *directory = argv[1], *mode = argv[2];
    int direct_rc = atoi(argv[3]), descendant_rc = atoi(argv[4]);
    long long deadline = now_ms() + atoi(argv[5]);
    pid_t wrapper = getppid();
    event(directory, "direct", wrapper);
    pid_t middle = fork();
    if (middle < 0) return 121;
    if (middle == 0) {
        event(directory, "middle", wrapper);
        pid_t descendant = fork();
        if (descendant < 0) _exit(122);
        if (descendant != 0) _exit(23);
        while (getppid() != wrapper && now_ms() < deadline) pause_ms();
        if (getppid() != wrapper) _exit(123);
        event(directory, "adopted", wrapper);
        while (!present(directory, "release") && now_ms() < deadline) pause_ms();
        /* The final write uses the log FD inherited from the real wrapper. */
        const char tail[] = "FC06_DESCENDANT_FINAL_BYTES\n";
        if (write(STDOUT_FILENO, tail, sizeof(tail) - 1) != (ssize_t)(sizeof(tail) - 1) || fsync(STDOUT_FILENO)) _exit(124);
        event(directory, "descendant_exit", wrapper);
        _exit(descendant_rc);
    }
    while (!present(directory, "adopted.json") && now_ms() < deadline) pause_ms();
    if (!present(directory, "adopted.json")) return 125;
    if (strcmp(mode, "signal") == 0) {
        while (now_ms() < deadline) pause_ms();
        return 126;
    }
    event(directory, "direct_exit", wrapper);
    return direct_rc;
}
