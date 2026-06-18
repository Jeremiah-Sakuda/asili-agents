"""Database models for Asili Agents.

These models represent the core entities in the system:
- Sellers (the micro-businesses using Asili)
- Products (items in the seller's catalog)
- Policies (business rules like margin floors)
- Conversations (customer interactions)
- Messages (individual messages in conversations)
- AgentDecisions (logged decisions for observability)
"""

from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, computed_field


class MessageDirection(str, Enum):
    """Direction of a message in a conversation."""

    INBOUND = "in"
    OUTBOUND = "out"


class MessageStatus(str, Enum):
    """Status of an outbound message."""

    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    SENT = "sent"
    FAILED = "failed"


class ConversationStatus(str, Enum):
    """Status of a conversation."""

    ACTIVE = "active"
    AWAITING_REPLY = "awaiting_reply"
    REPLIED = "replied"
    CLOSED = "closed"


class StockLevel(str, Enum):
    """Stock level indicators."""

    OUT_OF_STOCK = "out_of_stock"
    LOW = "low"
    HEALTHY = "healthy"
    OVERSTOCKED = "overstocked"


class OrderStatus(str, Enum):
    """Lifecycle of a DM-pipeline order.

    Mirrors how a micro-seller actually closes a sale in the DMs: a price is
    QUOTED, an invoice is sent (INVOICED), the customer pays (PAID), the seller
    ships (FULFILLED), or it falls through (CANCELLED). The money leaks at
    INVOICED — an invoice sent but never chased — which is what the invoice-nudge
    behavior targets.
    """

    QUOTED = "quoted"
    INVOICED = "invoiced"
    PAID = "paid"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"


class Seller(BaseModel):
    """A micro-seller using Asili Operations Team."""

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(..., description="Business name")
    category: str = Field(
        default="specialty goods",
        description="What the seller sells, used to frame agent prompts "
        "(e.g. 'specialty tea', 'shea butter & skincare', 'Levantine pantry goods')",
    )
    brand_voice: str = Field(
        default="friendly and helpful",
        description="Tone/style for AI-generated messages",
    )
    origin_country: str = Field(..., description="Country of origin (e.g., 'KE')")
    destination_country: str = Field(default="US", description="Primary destination market")
    currency: str = Field(default="USD", description="Display currency")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @computed_field
    @property
    def lane(self) -> str:
        """Trade lane description (e.g., 'KE → US')."""
        return f"{self.origin_country} → {self.destination_country}"


class Product(BaseModel):
    """A product in a seller's catalog."""

    id: UUID = Field(default_factory=uuid4)
    seller_id: UUID = Field(..., description="Reference to the seller")
    sku: str = Field(..., description="Stock keeping unit")
    name: str = Field(..., description="Product name")
    description: str = Field(..., description="Product description")
    category: str = Field(default="", description="Product category")
    origin: str = Field(default="", description="Product origin/source")

    # Pricing
    price: Decimal = Field(..., description="Retail price in seller's currency")
    cost: Decimal = Field(..., description="Landed cost (COGS)")

    # Inventory
    stock_quantity: int = Field(default=0, description="Current stock level")
    low_stock_threshold: int = Field(default=8, description="Threshold for 'low stock' warning")
    unit: str = Field(default="unit", description="Unit of measure (e.g., 'tin', 'bag')")

    # Metadata
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @computed_field
    @property
    def margin(self) -> Decimal:
        """Unit margin in currency."""
        return self.price - self.cost

    @computed_field
    @property
    def margin_percent(self) -> float:
        """Margin as a percentage of price."""
        if self.price == 0:
            return 0.0
        return float(self.margin / self.price)

    @computed_field
    @property
    def stock_level(self) -> StockLevel:
        """Human-readable stock level."""
        if self.stock_quantity <= 0:
            return StockLevel.OUT_OF_STOCK
        if self.stock_quantity <= self.low_stock_threshold:
            return StockLevel.LOW
        if self.stock_quantity > self.low_stock_threshold * 3:
            return StockLevel.OVERSTOCKED
        return StockLevel.HEALTHY

    @computed_field
    @property
    def is_in_stock(self) -> bool:
        """Whether the product is available for sale."""
        return self.stock_quantity > 0 and self.is_active


class Policy(BaseModel):
    """Business policies for a seller."""

    id: UUID = Field(default_factory=uuid4)
    seller_id: UUID = Field(..., description="Reference to the seller")

    # Pricing policies
    margin_floor: float = Field(default=0.45, description="Minimum acceptable margin (45% = 0.45)")
    bundle_discount_percent: float = Field(
        default=0.05, description="Discount for bundles (5% = 0.05)"
    )
    max_bundle_discount_percent: float = Field(
        default=0.10, description="Maximum bundle discount (10% = 0.10)"
    )

    # Shipping policies
    shipping_note: str = Field(
        default="Ships within 2-3 business days",
        description="Standard shipping information",
    )
    free_shipping_threshold: Decimal | None = Field(
        default=None, description="Order value for free shipping"
    )

    # Returns policy
    returns_note: str = Field(
        default="30-day returns for unopened items",
        description="Return policy summary",
    )

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Message(BaseModel):
    """A single message in a conversation."""

    id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID = Field(..., description="Parent conversation")
    direction: MessageDirection = Field(..., description="Inbound or outbound")
    sender_name: str = Field(..., description="Name of the sender")
    body: str = Field(..., description="Message content")
    status: MessageStatus = Field(default=MessageStatus.SENT)

    # Agent metadata (for outbound messages)
    agent_name: str | None = Field(default=None, description="Agent that generated this message")
    sources: list[str] = Field(
        default_factory=list, description="Data sources used to generate the message"
    )

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sent_at: datetime | None = Field(default=None)

    @computed_field
    @property
    def timestamp_display(self) -> str:
        """Human-readable timestamp."""
        ts = self.sent_at or self.created_at
        return ts.strftime("%-I:%M %p")


class Conversation(BaseModel):
    """A conversation with a customer."""

    id: UUID = Field(default_factory=uuid4)
    seller_id: UUID = Field(..., description="The seller handling this conversation")
    customer_name: str = Field(..., description="Customer's display name")
    customer_initials: str = Field(default="", description="Customer initials for avatar")
    channel: str = Field(default="Storefront chat", description="Communication channel")
    status: ConversationStatus = Field(default=ConversationStatus.ACTIVE)

    messages: list[Message] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def add_message(
        self,
        direction: MessageDirection,
        sender_name: str,
        body: str,
        **kwargs: Any,
    ) -> Message:
        """Add a message to the conversation."""
        message = Message(
            conversation_id=self.id,
            direction=direction,
            sender_name=sender_name,
            body=body,
            **kwargs,
        )
        self.messages.append(message)
        self.updated_at = datetime.now(UTC)
        return message

    @property
    def last_message_at(self) -> datetime:
        """Timestamp of the most recent message (or creation if none)."""
        if not self.messages:
            return self.created_at
        return max((m.sent_at or m.created_at) for m in self.messages)

    @property
    def last_direction(self) -> MessageDirection | None:
        """Direction of the most recent message, or None if empty."""
        if not self.messages:
            return None
        latest = max(self.messages, key=lambda m: m.sent_at or m.created_at)
        return latest.direction

    @property
    def is_open(self) -> bool:
        """Whether the conversation is still live (not closed)."""
        return self.status != ConversationStatus.CLOSED

    def hours_quiet(self, now: datetime) -> float:
        """Hours since the last message in this conversation."""
        delta = now - self.last_message_at
        return delta.total_seconds() / 3600.0


class Order(BaseModel):
    """A DM-pipeline order — the unit a follow-up or invoice nudge acts on.

    Deliberately lightweight: a micro-seller's "order" is usually a quote agreed
    in a DM, an invoice sent, and (hopefully) a payment. Amounts are Decimal so
    nudge copy can quote an exact figure without float drift.
    """

    id: UUID = Field(default_factory=uuid4)
    seller_id: UUID = Field(..., description="The seller this order belongs to")
    customer_name: str = Field(..., description="Customer's display name")
    conversation_id: UUID | None = Field(
        default=None, description="Conversation this order came from, if any"
    )
    description: str = Field(default="", description="What was ordered (e.g. '2 tins Purple Tea')")
    amount: Decimal = Field(..., description="Order total in the seller's currency")
    status: OrderStatus = Field(default=OrderStatus.QUOTED)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    invoiced_at: datetime | None = Field(default=None, description="When the invoice was sent")
    due_at: datetime | None = Field(default=None, description="When payment is due")
    paid_at: datetime | None = Field(default=None, description="When payment was received")

    @computed_field
    @property
    def is_unpaid(self) -> bool:
        """An invoice was sent but no payment has been recorded."""
        return self.status == OrderStatus.INVOICED and self.paid_at is None

    def is_overdue(self, now: datetime) -> bool:
        """Whether an unpaid invoice is past its due date as of ``now``.

        If no due date is set, an unpaid invoice is considered overdue once any
        time has passed since it was invoiced (the seller still wants it chased).
        """
        if not self.is_unpaid:
            return False
        if self.due_at is not None:
            return now >= self.due_at
        if self.invoiced_at is not None:
            return now > self.invoiced_at
        return False

    def hours_overdue(self, now: datetime) -> float:
        """Hours past due (from due_at, else invoiced_at). 0 if not overdue."""
        if not self.is_overdue(now):
            return 0.0
        reference = self.due_at or self.invoiced_at
        if reference is None:
            return 0.0
        return (now - reference).total_seconds() / 3600.0


class ChannelStatus(str, Enum):
    """Lifecycle of a seller's connection to a messaging channel."""

    PENDING = "pending"  # OAuth/embedded-signup started, not yet usable (e.g. awaiting review)
    CONNECTED = "connected"
    ERROR = "error"
    REVOKED = "revoked"


class ChannelConnection(BaseModel):
    """A seller's connection to one messaging channel (their own IG/WhatsApp/
    Telegram account). The access token is stored ENCRYPTED (a TokenVault blob),
    never in plaintext. ``external_account_id`` is the seller-side account that
    receives inbound (IG business id, WhatsApp phone-number id, or "telegram"),
    used to route an inbound webhook to the right seller.
    """

    seller_id: str = Field(..., description="The seller this connection belongs to")
    platform: str = Field(..., description="instagram | whatsapp | telegram")
    status: ChannelStatus = Field(default=ChannelStatus.PENDING)

    external_account_id: str | None = Field(
        default=None, description="Seller-side account id that receives inbound messages"
    )
    external_handle: str | None = Field(default=None, description="Display handle, e.g. @shop")

    encrypted_token: str | None = Field(
        default=None,
        description="TokenVault-encrypted access token (never plaintext, never logged)",
    )
    token_expires_at: datetime | None = Field(default=None)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentDecision(BaseModel):
    """A logged decision made by an agent.

    Used for observability, debugging, and demonstrating multi-agent collaboration.
    """

    id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID | None = Field(default=None)
    seller_id: UUID | None = Field(default=None)

    # Agent identification
    agent_name: str = Field(..., description="Name of the agent making the decision")
    agent_role: str = Field(default="", description="Role of the agent")
    step_type: str = Field(
        default="",
        description="Type of step (route, ground, compute, compose)",
    )

    # Decision details
    reasoning_trace: str = Field(..., description="Explanation of the decision")
    grounded_facts: list[str] = Field(
        default_factory=list,
        description="IDs of facts this decision verified against",
    )

    # Inputs and outputs
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)

    # API usage tracking
    model_used: str = Field(default="")
    tokens_used: int = Field(default=0)
    latency_ms: int = Field(default=0)

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @computed_field
    @property
    def timestamp_relative(self) -> str:
        """Relative timestamp for display (e.g., '+0.7s')."""
        # This would be computed relative to the conversation start
        # For now, return a placeholder
        return "+0.0s"
