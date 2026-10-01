"""Plain TCP relay inside the dev VM: 127.0.0.1:18000 -> host.lima.internal:8000.

Lets pipeline calls reach Splash with a localhost authority (Splash refuses
other Host values). Bytes are passed through unchanged. Lives in the repo so
the VM can still reach it after D-196 narrowed the mounts. Start it inside the
VM with `setsid nohup python3 lima/splash-relay.py >/tmp/relay.log 2>&1 &`
(plain nohup dies with the limactl shell); seat a role on it with
SANDBOX_LLM_HOST=127.0.0.1 SANDBOX_LLM_PORT=18000."""
import socket
import threading


def pipe(a: socket.socket, b: socket.socket) -> None:
    try:
        while (data := a.recv(65536)):
            b.sendall(data)
    except OSError:
        pass  # a peer closed or reset: the relay just ends this direction
    finally:
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass  # already shut down by the other direction


def main() -> None:
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 18000))
    srv.listen(64)
    while True:
        client, _ = srv.accept()
        upstream = socket.create_connection(("host.lima.internal", 8000))
        threading.Thread(target=pipe, args=(client, upstream), daemon=True).start()
        threading.Thread(target=pipe, args=(upstream, client), daemon=True).start()


if __name__ == "__main__":
    main()
