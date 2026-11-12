"""The entrance of the connector gateway (services/gateway).

The gateway takes a report in from its channel (today only the app), checks the input of that channel, stores the raw photo in the
raw bucket and hands the report over here in the format of `IncomingReport`, see `GatewaySubmission`. From here on the report runs
the same way as one that comes straight to `POST /v1/reports`: same rate limit, same retry safety, same graph, same answer.

Two locks:
- The gateway shows the shared key `GATEWAY_KEY` in the header `X-Gateway-Key`. Without that variable this endpoint does not
  exist (404), so a backend without a gateway is unchanged.
- The user is the one of the login. The gateway passes the user's token on, it never sends a user of its own.

The endpoint is for the compose network only: Caddy does not route `/internal` (deploy/Caddyfile).

Raw photos of a report that is not claimed here (the key or the token is refused, the rate limit, an invalid submission, or a
retry of a report that exists already) still belong to the gateway, and the gateway deletes them. Once a report is claimed, its
raw photos belong to the privacy layer, which deletes them after the sanitized copy exists.
"""

import hmac
import logging
from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from api.reports import Services, check_rate_limit, owned_record, payload_for
from auth.tokens import AccessClaims
from models.gateway_submission import GatewaySubmission
from models.incoming_report import IncomingReport

logger = logging.getLogger("ortsbild.api")

MAX_SUBMISSION_BYTES = 64 * 1024  # the submission holds refs, not photos, so it is small


def create_gateway_router(
    get_services: Callable[[], Services],
    current_user: Callable[..., AccessClaims],
    get_gateway_key: Callable[[], str | None],
    reports_per_hour: int = 20,
    tenant: str = "pilot",
) -> APIRouter:
    """The endpoint the gateway hands its reports to. `tenant` is set here, never taken from the gateway or the client."""

    def gateway_only(x_gateway_key: str | None = Header(default=None)) -> None:
        expected = get_gateway_key()
        if not expected:
            raise HTTPException(404, "Not Found")  # no gateway configured: the endpoint does not exist
        if not x_gateway_key or not hmac.compare_digest(x_gateway_key, expected):
            raise HTTPException(403, "not the gateway")

    router = APIRouter(prefix="/internal/v1", dependencies=[Depends(gateway_only)])

    @router.post("/reports")
    async def accept_from_gateway(request: Request, user: AccessClaims = Depends(current_user)) -> JSONResponse:
        """Run a report that the gateway took in, and answer exactly as `POST /v1/reports` does, the gateway relays the answer.

        The body is read as JSON by the contract model itself (strict, unknown fields are refused), not by FastAPI. The work runs
        in the thread pool like the app endpoint, so a long chain does not block the server.
        """
        body = await request.body()
        return await run_in_threadpool(accept, body, user)

    def accept(body: bytes, user: AccessClaims) -> JSONResponse:
        services = get_services()
        check_rate_limit(services, user, reports_per_hour)
        if len(body) > MAX_SUBMISSION_BYTES:
            raise HTTPException(413, "the submission is too big")
        try:
            submission = GatewaySubmission.model_validate_json(body)
        except ValidationError:
            raise HTTPException(422, "the report is not valid") from None
        if submission.source.type != "app":
            # TODO: Accept the email channel: the user is then the sender address (identifier_type "email"), not a login.
            raise HTTPException(422, "only reports of the app are accepted yet")

        owner_of_id = services.status_store.claim(
            submission.id, user.user_key, submission.client_report_id, submission.source.type, tenant
        )
        if owner_of_id != submission.id:  # a retry: answer with the first result, the gateway deletes its new raw photos
            return JSONResponse(payload_for(services, owned_record(services, owner_of_id, user)))

        try:
            report = IncomingReport(
                id=submission.id,
                received_at=submission.received_at,
                source=submission.source,
                location=submission.location,
                text=submission.text,
                photos=list(submission.photos),
                user={"identifier": user.user_key, "identifier_type": "user_key"},
            )
        except ValidationError:
            raise HTTPException(422, "the report is not valid") from None

        services.graph.invoke({"report": report})
        return JSONResponse(payload_for(services, owned_record(services, submission.id, user)))

    return router
