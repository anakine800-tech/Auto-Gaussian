/* Auto-G16 private Darwin adapter source. NOT BUILT / NOT QUALIFIED.
 * No Popen, alternate reaper, descendant scan, process group signal or retry.
 * The Python service gate denies loading this library in this candidate.
 */
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <spawn.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/event.h>
#include <sys/wait.h>
#include <unistd.h>

struct ag_child {
    pid_t pid;
    int queue, registered, resumed, owner, reaped, released, poisoned;
    int in, out, err;
    uint32_t history;
    int exited, exit_status;
    struct sigaction original_sigchld;
};

static int fail(struct ag_child *h, int error) {
    if (h) h->poisoned = 1;
    return error ? error : EIO;
}

int ag_reaper_check(struct ag_child *h) {
    struct sigaction current;
    if (sigaction(SIGCHLD, NULL, &current)) return fail(h, errno);
    /* Only the default disposition is supported. No user handler can reap. */
    if (current.sa_handler != SIG_DFL || (current.sa_flags & SA_NOCLDWAIT))
        return fail(h, EINVAL);
    if (h && (current.sa_handler != h->original_sigchld.sa_handler ||
              current.sa_flags != h->original_sigchld.sa_flags ||
              memcmp(&current.sa_mask, &h->original_sigchld.sa_mask, sizeof(sigset_t))))
        return fail(h, EINVAL);
    return 0;
}

/* The handle is assigned before any call which could leave a child behind. */
int ag_spawn(const char *config, const char *alias, const char *source,
             const char *cwd, struct ag_child **result) {
    struct ag_child *h = calloc(1, sizeof(*h));
    posix_spawnattr_t attr;
    posix_spawn_file_actions_t actions;
    int pipes[3][2] = {{-1,-1},{-1,-1},{-1,-1}};
    int error = 0, attr_ready = 0, actions_ready = 0;
    sigset_t mask, defaults;
    if (!h) return ENOMEM;
    h->pid = -1; h->queue = h->in = h->out = h->err = -1;
    *result = h;
    if (sigaction(SIGCHLD, NULL, &h->original_sigchld)) return fail(h, errno);
    if ((error = ag_reaper_check(h))) return error;
    if (!config || config[0] != '/' || !alias || alias[0] == '-' || !source || !cwd || cwd[0] != '/')
        return fail(h, EINVAL);
    h->queue = kqueue();
    if (h->queue < 0) return fail(h, errno);
    if (fcntl(h->queue, F_SETFD, FD_CLOEXEC) < 0) return fail(h, errno);
    for (int i = 0; i < 3; i++) {
        if (pipe(pipes[i])) { error = errno; goto done; }
        for (int j = 0; j < 2; j++) {
            if (pipes[i][j] <= 2 || fcntl(pipes[i][j], F_SETFD, FD_CLOEXEC) < 0) {
                error = EINVAL; goto done;
            }
        }
    }
    if ((error = posix_spawnattr_init(&attr))) goto done;
    attr_ready = 1;
    if ((error = posix_spawn_file_actions_init(&actions))) goto done;
    actions_ready = 1;
    sigemptyset(&mask); sigemptyset(&defaults);
    for (int n = 1; n < NSIG; n++) if (n != SIGKILL && n != SIGSTOP) sigaddset(&defaults, n);
    if ((error = posix_spawnattr_setsigmask(&attr, &mask)) ||
        (error = posix_spawnattr_setsigdefault(&attr, &defaults)) ||
        (error = posix_spawnattr_setflags(&attr, POSIX_SPAWN_START_SUSPENDED |
                   POSIX_SPAWN_SETSID | POSIX_SPAWN_CLOEXEC_DEFAULT |
                   POSIX_SPAWN_SETSIGMASK | POSIX_SPAWN_SETSIGDEF)) ||
        (error = posix_spawn_file_actions_adddup2(&actions, pipes[0][0], 0)) ||
        (error = posix_spawn_file_actions_adddup2(&actions, pipes[1][1], 1)) ||
        (error = posix_spawn_file_actions_adddup2(&actions, pipes[2][1], 2)) ||
        (error = posix_spawn_file_actions_addchdir_np(&actions, cwd))) goto done;
    char *argv[] = {"/usr/bin/ssh", "-F", (char *)config, "--", (char *)alias, (char *)source, NULL};
    char *env[] = {"LANG=C", "LC_ALL=C", "PYTHONNOUSERSITE=1", "PYTHONUTF8=1", NULL};
    error = posix_spawn(&h->pid, "/usr/bin/ssh", &actions, &attr, argv, env);
    if (!error) {
        h->in = pipes[0][1]; pipes[0][1] = -1;
        h->out = pipes[1][0]; pipes[1][0] = -1;
        h->err = pipes[2][0]; pipes[2][0] = -1;
        int retained[] = {h->in, h->out, h->err};
        for (int i = 0; i < 3; i++) {
            int flags = fcntl(retained[i], F_GETFL);
            if (flags < 0 || fcntl(retained[i], F_SETFL, flags | O_NONBLOCK) < 0) {
                error = errno; break;
            }
        }
    }
done:
    if (actions_ready) posix_spawn_file_actions_destroy(&actions);
    if (attr_ready) posix_spawnattr_destroy(&attr);
    for (int i = 0; i < 3; i++) for (int j = 0; j < 2; j++)
        if (pipes[i][j] >= 0) close(pipes[i][j]);
    return error ? fail(h, error) : 0;
}

int ag_register(struct ag_child *h) {
    struct kevent change, receipt;
    struct timespec zero = {0, 0};
    if (!h || h->pid <= 0 || h->registered || h->poisoned) return fail(h, EINVAL);
    EV_SET(&change, h->pid, EVFILT_PROC, EV_ADD | EV_ENABLE | EV_RECEIPT,
           NOTE_FORK | NOTE_EXEC | NOTE_EXIT | NOTE_EXITSTATUS, 0, h);
    int count = kevent(h->queue, &change, 1, &receipt, 1, &zero);
    if (count != 1 || receipt.ident != (uintptr_t)h->pid || receipt.filter != EVFILT_PROC ||
        !(receipt.flags & EV_ERROR) || receipt.data != 0 || receipt.udata != h)
        return fail(h, count < 0 ? errno : EIO);
    h->registered = 1;
    return 0;
}

int ag_resume(struct ag_child *h) {
    if (!h || !h->registered || h->resumed || h->reaped || h->poisoned) return fail(h, EINVAL);
    int error = ag_reaper_check(h);
    if (error) return error;
    if (kill(h->pid, SIGCONT)) return fail(h, errno);
    h->resumed = 1;
    return 0;
}

int ag_owner(struct ag_child *h) {
    if (!h || !h->resumed || h->owner || h->poisoned) return fail(h, EINVAL);
    h->owner = 1;
    return 0;
}

static int normalize_wait(int raw, int *status) {
    if (WIFEXITED(raw)) *status = WEXITSTATUS(raw);
    else if (WIFSIGNALED(raw)) *status = -WTERMSIG(raw);
    else return EIO;
    return 0;
}

int ag_observe(struct ag_child *h, int *has_exit, int *status, uint32_t *history) {
    struct kevent events[16];
    struct timespec zero = {0, 0};
    if (!h || !h->registered || !h->owner || h->reaped || h->released) return fail(h, EINVAL);
    int error = ag_reaper_check(h);
    if (error) return error;
    int count = kevent(h->queue, NULL, 0, events, 16, &zero);
    if (count < 0) return fail(h, errno);
    for (int i = 0; i < count; i++) {
        struct kevent *event = &events[i];
        if (event->ident != (uintptr_t)h->pid || event->filter != EVFILT_PROC ||
            event->udata != h || (event->flags & EV_ERROR)) return fail(h, EIO);
        h->history |= event->fflags;
        if (event->fflags & NOTE_EXIT) {
            int value;
            if (!(event->fflags & NOTE_EXITSTATUS) || normalize_wait((int)event->data, &value))
                return fail(h, EIO);
            if (h->exited && value != h->exit_status) return fail(h, EIO);
            h->exited = 1; h->exit_status = value;
        }
    }
    *has_exit = h->exited; *status = h->exit_status; *history = h->history;
    if (h->history & (NOTE_FORK | NOTE_EXEC)) return fail(h, ECHILD);
    return h->poisoned ? EIO : 0;
}

int ag_peek(struct ag_child *h, int *ready, int *status) {
    siginfo_t info;
    memset(&info, 0, sizeof(info));
    if (!h || !h->registered || h->reaped || h->poisoned) return fail(h, EINVAL);
    int error = ag_reaper_check(h);
    if (error) return error;
    if (waitid(P_PID, (id_t)h->pid, &info, WNOWAIT | WNOHANG | WEXITED)) return fail(h, errno);
    *ready = info.si_pid != 0;
    if (!*ready) return 0;
    if (info.si_pid != h->pid) return fail(h, EIO);
    if (info.si_code == CLD_EXITED) *status = info.si_status;
    else if (info.si_code == CLD_KILLED || info.si_code == CLD_DUMPED) *status = -info.si_status;
    else return fail(h, EIO);
    return 0;
}

int ag_reap(struct ag_child *h, int *status) {
    int present, expected, has_exit, event_status, raw;
    uint32_t history;
    if (!h || h->reaped || h->poisoned) return fail(h, EINVAL);
    int error = ag_observe(h, &has_exit, &event_status, &history);
    if (error || !has_exit) return fail(h, error);
    error = ag_peek(h, &present, &expected);
    if (error || !present || expected != event_status) return fail(h, error);
    pid_t result = waitpid(h->pid, &raw, WNOHANG);
    if (result != h->pid) return fail(h, result < 0 ? errno : EIO);
    h->reaped = 1; /* Record irreversible reap before subsequent validation. */
    if (normalize_wait(raw, status) || *status != expected) return fail(h, EIO);
    return 0;
}

int ag_pid(struct ag_child *h) { return h ? h->pid : -1; }
int ag_fd(struct ag_child *h, int stream) {
    if (!h || h->released) return -1;
    return stream == 0 ? h->in : stream == 1 ? h->out : stream == 2 ? h->err : -1;
}
int ag_close_input(struct ag_child *h) {
    if (!h || h->released) return EINVAL;
    if (h->in < 0) return 0;
    int fd = h->in; h->in = -1;
    return close(fd) ? fail(h, errno) : 0;
}
int ag_release(struct ag_child *h) {
    if (!h || !h->reaped || h->poisoned || h->released) return fail(h, EINVAL);
    int fds[] = {h->in, h->out, h->err, h->queue};
    h->released = 1;
    for (int i = 0; i < 4; i++) if (fds[i] >= 0 && close(fds[i])) return fail(h, errno);
    /* Retain the tombstone allocation; no stale handle can address a new child. */
    return 0;
}
