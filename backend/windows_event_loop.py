"""Boucle Proactor Windows qui réarme accept() après WinError 64."""
from __future__ import annotations

import asyncio
from asyncio import exceptions, trsock


RETRYABLE_ACCEPT_WINERRORS = frozenset({64})
ACCEPT_RETRY_DELAY_SECONDS = 0.1
_BaseWindowsLoop = getattr(asyncio, "ProactorEventLoop", asyncio.SelectorEventLoop)


class ResilientProactorEventLoop(_BaseWindowsLoop):
    """Préserve les sous-processus Proactor sans perdre le listener HTTP."""

    def _start_serving(
        self,
        protocol_factory,
        sock,
        sslcontext=None,
        server=None,
        backlog=100,
        ssl_handshake_timeout=None,
        ssl_shutdown_timeout=None,
    ):
        def accept_next(future=None):
            try:
                if future is not None:
                    conn, addr = future.result()
                    protocol = protocol_factory()
                    if sslcontext is not None:
                        self._make_ssl_transport(
                            conn,
                            protocol,
                            sslcontext,
                            server_side=True,
                            extra={"peername": addr},
                            server=server,
                            ssl_handshake_timeout=ssl_handshake_timeout,
                            ssl_shutdown_timeout=ssl_shutdown_timeout,
                        )
                    else:
                        self._make_socket_transport(
                            conn,
                            protocol,
                            extra={"peername": addr},
                            server=server,
                        )
                if self.is_closed():
                    return
                next_future = self._proactor.accept(sock)
            except OSError as exc:
                if sock.fileno() == -1:
                    return
                self.call_exception_handler(
                    {
                        "message": "Accept failed on a socket",
                        "exception": exc,
                        "socket": trsock.TransportSocket(sock),
                    }
                )
                if getattr(exc, "winerror", None) in RETRYABLE_ACCEPT_WINERRORS:
                    self.call_later(ACCEPT_RETRY_DELAY_SECONDS, accept_next)
                else:
                    sock.close()
            except exceptions.CancelledError:
                sock.close()
            else:
                self._accept_futures[sock.fileno()] = next_future
                next_future.add_done_callback(accept_next)

        self.call_soon(accept_next)
