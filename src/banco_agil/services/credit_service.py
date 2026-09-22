from datetime import UTC, datetime
from decimal import Decimal

from pydantic import TypeAdapter, ValidationError

from banco_agil.models.domain import CreditRequest, CreditRequestStatus, PositiveMoney
from banco_agil.models.errors import InvalidCreditLimitError, RepositoryError
from banco_agil.repositories.credit_request_repository import CreditRequestRepository
from banco_agil.repositories.customer_repository import CustomerRepository
from banco_agil.repositories.score_range_repository import ScoreRangeRepository


class CreditService:
    def __init__(
        self,
        customers: CustomerRepository,
        requests: CreditRequestRepository | None = None,
        ranges: ScoreRangeRepository | None = None,
    ):
        self.customers = customers
        self.requests = requests or CreditRequestRepository(customers.path.parent)
        self.ranges = ranges or ScoreRangeRepository(customers.path.parent)

    def get_limit(self, authenticated_cpf: str) -> Decimal:
        self.recover_pending(authenticated_cpf)
        return self.customers.require(authenticated_cpf).limite_credito

    def recover_pending(self, cpf: str) -> list[CreditRequest]:
        """Retoma escrita interrompida antes de permitir outra operação de crédito.

        Sem concorrência: limite solicitado indica que a primeira escrita ocorreu;
        snapshot original indica que ainda falta avaliar/aplicar. Outro valor bloqueia.
        """
        recovered = []
        for request in self.requests.read():
            if request.cpf_cliente == cpf and request.status_pedido == CreditRequestStatus.PENDING:
                recovered.append(self._evaluate(request))
        return recovered

    def request_increase(self, cpf: str, requested_limit: Decimal) -> CreditRequest:
        try:
            amount = TypeAdapter(PositiveMoney).validate_python(requested_limit)
        except ValidationError as exc:
            raise InvalidCreditLimitError() from exc
        recovered = self.recover_pending(cpf)
        if recovered and recovered[-1].novo_limite_solicitado == amount:
            return recovered[-1]
        customer = self.customers.require(cpf)
        request = CreditRequest(
            cpf_cliente=customer.cpf,
            data_hora_solicitacao=datetime.now(UTC),
            limite_atual=customer.limite_credito,
            novo_limite_solicitado=amount,
        )
        self.requests.add(request)
        return self._evaluate(request)

    def _evaluate(self, request: CreditRequest) -> CreditRequest:
        customer = self.customers.require(request.cpf_cliente)
        amount, original = request.novo_limite_solicitado, request.limite_atual
        if customer.limite_credito == amount and amount > original:
            # Recuperação após atualizar cliente e antes de finalizar solicitação.
            approved = True
        elif customer.limite_credito == original:
            maximum = self.ranges.for_score(customer.score_credito).limite_maximo
            approved = original < amount <= maximum
            if approved:
                customer.limite_credito = amount
                self.customers.save(customer)
        else:
            raise RepositoryError()
        request.status_pedido = (
            CreditRequestStatus.APPROVED if approved else CreditRequestStatus.REJECTED
        )
        self.requests.save(request)
        return request
