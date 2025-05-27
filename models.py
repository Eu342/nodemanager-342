from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase
from datetime import datetime

class Base(AsyncAttrs, DeclarativeBase):
    pass

class Inbound(Base):
    __tablename__ = "inbounds"
    __table_args__ = {'schema': 'public'}  # Явно указываем схему public
    id = Column(Integer, primary_key=True)
    tag = Column(String(100), nullable=False)  # Поле tag для инбаундов

class Server(Base):
    __tablename__ = "servers"
    id = Column(Integer, primary_key=True)
    ip = Column(String(15), nullable=False)
    inbound = Column(String(100), nullable=False)
    install_date = Column(DateTime, default=datetime.utcnow)