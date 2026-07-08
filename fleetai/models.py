from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text
from .db import Base


class Car(Base):
    __tablename__ = "cars"

    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True, nullable=False)
    brand = Column(String)
    model = Column(String)
    plate = Column(String)
    year = Column(Integer)
    purchase_date = Column(String)
    purchase_price = Column(Integer, default=0)
    purchase_mileage = Column(Integer, default=0)
    current_mileage = Column(Integer, default=0)
    status = Column(String, default="Работает")
    driver = Column(String, default="")
    owner_type = Column(String, default="own")
    investor_name = Column(String, default="")
    investor_percent = Column(Integer, default=0)
    settlement_day = Column(Integer, default=15)


class Operation(Base):
    __tablename__ = "operations"

    id = Column(Integer, primary_key=True)
    date = Column(DateTime, default=datetime.now)
    car_code = Column(String)
    type = Column(String)
    category = Column(String)
    description = Column(String)
    amount = Column(Integer, default=0)
    mileage = Column(Integer)
    raw_message = Column(Text)


class Income(Base):
    __tablename__ = "income"

    id = Column(Integer, primary_key=True)
    operation_id = Column(Integer)
    car_code = Column(String)
    date = Column(DateTime, default=datetime.now)
    amount = Column(Integer, default=0)
    income_type = Column(String)


class Expense(Base):
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True)
    operation_id = Column(Integer)
    car_code = Column(String)
    date = Column(DateTime, default=datetime.now)
    category = Column(String)
    amount = Column(Integer, default=0)
    share_type = Column(String, default="shared")


class Part(Base):
    __tablename__ = "parts"

    id = Column(Integer, primary_key=True)
    car_code = Column(String)
    operation_id = Column(Integer)
    part_name = Column(String)
    brand = Column(String)
    position = Column(String)
    price = Column(Integer, default=0)
    labor = Column(Integer, default=0)
    install_date = Column(DateTime, default=datetime.now)
    install_mileage = Column(Integer)
    remove_date = Column(DateTime)
    remove_mileage = Column(Integer)
    status = Column(String, default="Установлена")


class CarInvestment(Base):
    __tablename__ = "car_investments"

    id = Column(Integer, primary_key=True)
    operation_id = Column(Integer)
    date = Column(DateTime, default=datetime.now)
    car_code = Column(String)
    category = Column(String, default="Доп. вложение")
    description = Column(String)
    amount = Column(Integer, default=0)
    investor_name = Column(String, default="")
    raw_message = Column(Text)


class InvestorInvestment(Base):
    __tablename__ = "investor_investments"

    id = Column(Integer, primary_key=True)
    operation_id = Column(Integer)
    date = Column(DateTime, default=datetime.now)
    investor_name = Column(String)
    car_code = Column(String)
    amount = Column(Integer, default=0)
    percent = Column(Integer, default=0)
    comment = Column(Text)


class InvestorPayout(Base):
    __tablename__ = "investor_payouts"

    id = Column(Integer, primary_key=True)
    operation_id = Column(Integer)
    date = Column(DateTime, default=datetime.now)
    investor_name = Column(String)
    car_code = Column(String)
    amount = Column(Integer, default=0)
    comment = Column(Text)


class InvestorSettlement(Base):
    __tablename__ = "investor_settlements"

    id = Column(Integer, primary_key=True)
    operation_id = Column(Integer)
    date = Column(DateTime, default=datetime.now)
    investor_name = Column(String)
    car_code = Column(String)
    total_cost = Column(Integer, default=0)
    investor_paid = Column(Integer, default=0)
    park_paid = Column(Integer, default=0)
    investor_debt_to_park = Column(Integer, default=0)
    park_debt_to_investor = Column(Integer, default=0)
    description = Column(String)
    comment = Column(Text)


class Mileage(Base):
    __tablename__ = "mileage"

    id = Column(Integer, primary_key=True)
    car_code = Column(String)
    date = Column(DateTime, default=datetime.now)
    mileage = Column(Integer)
    source = Column(Text)


class Downtime(Base):
    __tablename__ = "downtime"

    id = Column(Integer, primary_key=True)
    operation_id = Column(Integer)
    car_code = Column(String)
    start_date = Column(DateTime, default=datetime.now)
    end_date = Column(DateTime)
    days = Column(Integer, default=0)
    reason = Column(String)
    comment = Column(Text)
    active = Column(Integer, default=0)


class SettlementPeriod(Base):
    __tablename__ = "settlement_periods"

    id = Column(Integer, primary_key=True)
    car_code = Column(String)
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    income = Column(Integer, default=0)
    expenses = Column(Integer, default=0)
    investments = Column(Integer, default=0)
    profit = Column(Integer, default=0)
    investor_name = Column(String, default="")
    investor_percent = Column(Integer, default=0)
    investor_amount = Column(Integer, default=0)
    owner_amount = Column(Integer, default=0)
    downtime_days = Column(Integer, default=0)
    closed_at = Column(DateTime, default=datetime.now)
    comment = Column(Text)
