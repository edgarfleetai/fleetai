        session = Session()

        try:
            car = find_car(session, code)

            if not car:
                raise ValueError(
                    f"Машина {code} не найдена"
                )

            # 4. Защита от повторного webhook.
            # PaymentId сохраняем в raw_message.
            payment_marker = f"[TBANK_PAYMENT:{payment_id}]"

            existing = (
                session.query(Operation)
                .filter(Operation.raw_message.contains(payment_marker))
                .first()
            )

            if existing:
                print(
                    f"T-BANK WEBHOOK: payment {payment_id} "
                    f"already processed",
                    flush=True,
                )
                return "OK", 200

            now = moscow_now().replace(tzinfo=None)
            payment_row = session.query(DriverBankPayment).filter(DriverBankPayment.payment_id == payment_id).first()
            wallet_amount = int(payment_row.amount or 0) if payment_row else amount

            # 5. На баланс зачисляется выбранная сумма; amount ниже — реальные деньги банка
            wallet_tx = DriverWalletTransaction(
                driver_name=car.driver or "",
                car_code=car.code,
                amount=wallet_amount,
                transaction_type="topup",
                source="tbank",
                comment=f"Оплата через T-Банк · {payment_id}",
                date=now,
            )
            session.add(wallet_tx)

            # 6. Записываем доход в общий финансовый учёт
            op = Operation(
                date=now,
                car_code=car.code,
                type="income",
                category="Аренда",
                description=(
                    f"Оплата аренды водителем "
                    f"{car.driver or ''} через T-Банк"
                ),
                amount=amount,
                raw_message=(
                    f"{payment_marker} "
                    f"{order_id} "
                    f"{car.code} +{amount} ₽"
                ),
            )

            session.add(op)
            session.flush()

            session.add(
                Income(
                    operation_id=op.id,
                    car_code=car.code,
                    date=now,
                    amount=amount,
                    income_type="Оплата аренды через T-Банк",
                )
            )

            # V7: аренда списывается ежедневно отдельными операциями кошелька.
            payment_applied = 0
            if payment_row:
                payment_row.status = "paid"
                payment_row.paid_at = now

            session.commit()

            print(
                f"T-BANK PAYMENT ACCEPTED: "
                f"car={car.code}, "
                f"amount={amount}, "
                f"payment_id={payment_id}, "
                f"rent_applied={payment_applied}",
                flush=True,
            )

            return "OK", 200

        except Exception:
            session.rollback()
            raise

        finally:
            session.close()

    except Exception as error:
        print(
            "T-BANK WEBHOOK ERROR:",
            str(error),
            flush=True,
        )
        return "ERROR", 500
