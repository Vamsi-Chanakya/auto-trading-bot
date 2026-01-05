"""
SQLite Database Models for Auto Trading App

Tables:
- trades: All executed trades (buy/sell)
- holdings: Current positions
- signals: Generated trading signals (pending/executed/rejected)
- portfolio_snapshots: Daily portfolio value snapshots
- audit_log: All system actions for compliance
"""

from datetime import datetime
from typing import Optional, List
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text, Enum as SQLEnum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import enum
import os

# Database path
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "trades.db")

Base = declarative_base()


class TradeAction(enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class SignalStatus(enum.Enum):
    PENDING = "PENDING"          # Awaiting user approval
    APPROVED = "APPROVED"        # User approved, ready to execute
    REJECTED = "REJECTED"        # User rejected
    EXECUTED = "EXECUTED"        # Trade completed
    EXPIRED = "EXPIRED"          # Approval timeout
    CANCELLED = "CANCELLED"      # System cancelled (e.g., price moved too much)


class Trade(Base):
    """Record of all executed trades."""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), nullable=False, index=True)
    action = Column(String(4), nullable=False)  # BUY or SELL
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)  # Execution price
    total_value = Column(Float, nullable=False)  # quantity * price
    order_id = Column(String(50), nullable=True)  # Webull order ID
    signal_id = Column(Integer, nullable=True)  # Reference to signal that triggered this

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    executed_at = Column(DateTime, nullable=True)

    # For sells, track profit/loss
    buy_price = Column(Float, nullable=True)  # Original buy price (for sells)
    profit_loss = Column(Float, nullable=True)  # Realized P&L
    profit_loss_pct = Column(Float, nullable=True)  # P&L percentage
    hold_days = Column(Integer, nullable=True)  # Days held (for sells)

    # Metadata
    notes = Column(Text, nullable=True)


class Holding(Base):
    """Current portfolio holdings."""
    __tablename__ = "holdings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), nullable=False, unique=True, index=True)
    quantity = Column(Integer, nullable=False)
    avg_buy_price = Column(Float, nullable=False)
    total_cost = Column(Float, nullable=False)

    # Current values (updated periodically)
    current_price = Column(Float, nullable=True)
    current_value = Column(Float, nullable=True)
    unrealized_pl = Column(Float, nullable=True)
    unrealized_pl_pct = Column(Float, nullable=True)

    # Risk management
    stop_loss_price = Column(Float, nullable=True)  # -5% from buy
    take_profit_price = Column(Float, nullable=True)  # +10% from buy

    # Timestamps
    first_bought_at = Column(DateTime, nullable=False)
    last_updated_at = Column(DateTime, default=datetime.utcnow)


class Signal(Base):
    """Trading signals awaiting or processed."""
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), nullable=False, index=True)
    action = Column(String(4), nullable=False)  # BUY or SELL

    # Signal details
    suggested_price = Column(Float, nullable=False)
    suggested_quantity = Column(Integer, nullable=False)
    reason = Column(Text, nullable=False)  # Why this signal was generated

    # Status tracking
    status = Column(String(20), default=SignalStatus.PENDING.value)

    # Approval flow
    sms_sent_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)  # 15 min timeout
    user_response = Column(String(10), nullable=True)  # Y/N/M
    responded_at = Column(DateTime, nullable=True)

    # Execution
    trade_id = Column(Integer, nullable=True)  # If executed, link to trade

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PortfolioSnapshot(Base):
    """Daily portfolio value snapshots for tracking performance."""
    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(DateTime, nullable=False, index=True)

    # Values
    total_value = Column(Float, nullable=False)  # Cash + holdings value
    cash_balance = Column(Float, nullable=False)
    holdings_value = Column(Float, nullable=False)

    # Performance
    daily_pl = Column(Float, nullable=True)  # Change from previous day
    daily_pl_pct = Column(Float, nullable=True)
    total_pl = Column(Float, nullable=True)  # Change from initial $1000
    total_pl_pct = Column(Float, nullable=True)

    # Drawdown tracking
    peak_value = Column(Float, nullable=True)  # Highest value so far
    drawdown = Column(Float, nullable=True)  # Current drawdown from peak
    drawdown_pct = Column(Float, nullable=True)

    # Holdings count
    num_holdings = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    """Audit trail of all system actions."""
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    # Action details
    action_type = Column(String(50), nullable=False)  # e.g., SIGNAL_CREATED, TRADE_EXECUTED, SMS_SENT
    symbol = Column(String(10), nullable=True)
    description = Column(Text, nullable=False)

    # Related IDs
    trade_id = Column(Integer, nullable=True)
    signal_id = Column(Integer, nullable=True)

    # Additional data (JSON string)
    extra_data = Column(Text, nullable=True)


class TradingState(Base):
    """Global trading state (e.g., pause status)."""
    __tablename__ = "trading_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(50), nullable=False, unique=True)
    value = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Database:
    """Database manager class."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.engine = None
        self.SessionLocal = None
        self._initialize()

    def _initialize(self):
        """Initialize database connection and create tables."""
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        # Create engine
        self.engine = create_engine(f"sqlite:///{self.db_path}", echo=False)

        # Create all tables
        Base.metadata.create_all(self.engine)

        # Create session factory
        self.SessionLocal = sessionmaker(bind=self.engine)

    def get_session(self) -> Session:
        """Get a new database session."""
        return self.SessionLocal()

    # Trade operations
    def add_trade(self, session: Session, trade: Trade) -> Trade:
        """Add a new trade record."""
        session.add(trade)
        session.commit()
        session.refresh(trade)
        return trade

    def get_trades(self, session: Session, symbol: Optional[str] = None,
                   limit: int = 100) -> List[Trade]:
        """Get trade history."""
        query = session.query(Trade)
        if symbol:
            query = query.filter(Trade.symbol == symbol)
        return query.order_by(Trade.created_at.desc()).limit(limit).all()

    # Holding operations
    def get_holdings(self, session: Session) -> List[Holding]:
        """Get all current holdings."""
        return session.query(Holding).all()

    def get_holding(self, session: Session, symbol: str) -> Optional[Holding]:
        """Get a specific holding."""
        return session.query(Holding).filter(Holding.symbol == symbol).first()

    def update_or_create_holding(self, session: Session, symbol: str,
                                  quantity: int, avg_price: float,
                                  stop_loss: float, take_profit: float) -> Holding:
        """Update existing holding or create new one."""
        holding = self.get_holding(session, symbol)

        if holding:
            # Update existing
            total_shares = holding.quantity + quantity
            total_cost = (holding.total_cost) + (quantity * avg_price)
            holding.quantity = total_shares
            holding.avg_buy_price = total_cost / total_shares
            holding.total_cost = total_cost
            holding.stop_loss_price = stop_loss
            holding.take_profit_price = take_profit
            holding.last_updated_at = datetime.utcnow()
        else:
            # Create new
            holding = Holding(
                symbol=symbol,
                quantity=quantity,
                avg_buy_price=avg_price,
                total_cost=quantity * avg_price,
                stop_loss_price=stop_loss,
                take_profit_price=take_profit,
                first_bought_at=datetime.utcnow()
            )
            session.add(holding)

        session.commit()
        session.refresh(holding)
        return holding

    def remove_holding(self, session: Session, symbol: str) -> bool:
        """Remove a holding (after selling)."""
        holding = self.get_holding(session, symbol)
        if holding:
            session.delete(holding)
            session.commit()
            return True
        return False

    # Signal operations
    def add_signal(self, session: Session, signal: Signal) -> Signal:
        """Add a new trading signal."""
        session.add(signal)
        session.commit()
        session.refresh(signal)
        return signal

    def get_pending_signals(self, session: Session) -> List[Signal]:
        """Get all pending signals awaiting approval."""
        return session.query(Signal).filter(
            Signal.status == SignalStatus.PENDING.value
        ).all()

    def update_signal_status(self, session: Session, signal_id: int,
                             status: SignalStatus, response: Optional[str] = None) -> Optional[Signal]:
        """Update signal status."""
        signal = session.query(Signal).filter(Signal.id == signal_id).first()
        if signal:
            signal.status = status.value
            if response:
                signal.user_response = response
                signal.responded_at = datetime.utcnow()
            signal.updated_at = datetime.utcnow()
            session.commit()
            session.refresh(signal)
        return signal

    # Audit log operations
    def log_action(self, session: Session, action_type: str, description: str,
                   symbol: Optional[str] = None, trade_id: Optional[int] = None,
                   signal_id: Optional[int] = None, extra_data: Optional[str] = None):
        """Log an action to audit trail."""
        log_entry = AuditLog(
            action_type=action_type,
            symbol=symbol,
            description=description,
            trade_id=trade_id,
            signal_id=signal_id,
            extra_data=extra_data
        )
        session.add(log_entry)
        session.commit()

    # Trading state operations
    def get_state(self, session: Session, key: str) -> Optional[str]:
        """Get a trading state value."""
        state = session.query(TradingState).filter(TradingState.key == key).first()
        return state.value if state else None

    def set_state(self, session: Session, key: str, value: str):
        """Set a trading state value."""
        state = session.query(TradingState).filter(TradingState.key == key).first()
        if state:
            state.value = value
        else:
            state = TradingState(key=key, value=value)
            session.add(state)
        session.commit()

    # Portfolio snapshot operations
    def add_snapshot(self, session: Session, snapshot: PortfolioSnapshot) -> PortfolioSnapshot:
        """Add a portfolio snapshot."""
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)
        return snapshot

    def get_latest_snapshot(self, session: Session) -> Optional[PortfolioSnapshot]:
        """Get the most recent portfolio snapshot."""
        return session.query(PortfolioSnapshot).order_by(
            PortfolioSnapshot.date.desc()
        ).first()


# Singleton instance
_db_instance = None

def get_database() -> Database:
    """Get or create the database instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance
