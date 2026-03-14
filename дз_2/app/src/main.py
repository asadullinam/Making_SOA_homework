from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from core.config import settings
from core.db import get_db
from core.dependencies import get_current_user, require_roles
from core.errors import ApiError
from core.logging import log_requests
from core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
    verify_token,
)
from generated.models import (
    AuthLoginRequest,
    AuthRefreshRequest,
    AuthRegisterRequest,
    AuthRegisterResponse,
    OrderCreateRequest,
    OrderItemResponse,
    OrderResponse,
    OrderUpdateRequest,
    ProductCreate,
    ProductListResponse,
    ProductResponse,
    ProductUpdate,
    PromoCodeCreate,
    PromoCodeResponse,
    TokenResponse,
)
from models import (
    DiscountType,
    OperationType,
    Order,
    OrderItem,
    OrderStatus,
    Product,
    ProductStatus,
    PromoCode,
    User,
    UserOperation,
    UserRole,
)

app = FastAPI(title="Marketplace API")
app.middleware("http")(log_requests)


@app.exception_handler(ApiError)
async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error_code": exc.error_code,
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    fields = []
    for err in exc.errors():
        loc = [str(part) for part in err.get("loc", []) if part != "body"]
        field = ".".join(loc) if loc else "body"
        fields.append({"field": field, "message": err.get("msg", "Invalid value")})

    return JSONResponse(
        status_code=400,
        content={
            "error_code": "VALIDATION_ERROR",
            "message": "Validation error",
            "details": {"fields": fields},
        },
    )


def _to_product_response(product: Product) -> ProductResponse:
    return ProductResponse(
        id=str(product.id),
        name=product.name,
        description=product.description,
        price=product.price,
        stock=product.stock,
        category=product.category,
        status=product.status.value,
        seller_id=str(product.seller_id),
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


def _to_order_response(order: Order) -> OrderResponse:
    items = [
        OrderItemResponse(
            id=str(item.id),
            product_id=str(item.product_id),
            quantity=item.quantity,
            price_at_order=item.price_at_order,
        )
        for item in order.items
    ]
    return OrderResponse(
        id=str(order.id),
        user_id=str(order.user_id),
        status=order.status.value,
        promo_code_id=str(order.promo_code_id) if order.promo_code_id else None,
        total_amount=order.total_amount,
        discount_amount=order.discount_amount,
        items=items,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _require_order_owner(order: Order, user: User) -> None:
    if user.role != UserRole.ADMIN and order.user_id != user.id:
        raise ApiError("ORDER_OWNERSHIP_VIOLATION", 403, "Order ownership violation")


def _require_product_owner(product: Product, user: User) -> None:
    if user.role == UserRole.SELLER and product.seller_id != user.id:
        raise ApiError("ACCESS_DENIED", 403, "Access denied")


def _check_rate_limit(db: Session, user_id: str, op_type: OperationType) -> None:
    last_op = (
        db.query(UserOperation)
        .filter(UserOperation.user_id == user_id, UserOperation.operation_type == op_type)
        .order_by(UserOperation.created_at.desc())
        .first()
    )
    if not last_op:
        return

    now = datetime.now(timezone.utc)
    delta = timedelta(minutes=settings.order_rate_limit_minutes)
    if last_op.created_at and now - last_op.created_at < delta:
        raise ApiError("ORDER_LIMIT_EXCEEDED", 429, "Order rate limit exceeded")


def _validate_promo_basic(promo: PromoCode, *, allow_exhausted_for_existing: bool = False) -> None:
    now = datetime.now(timezone.utc)
    is_exhausted = promo.current_uses >= promo.max_uses
    if not promo.active or (is_exhausted and not allow_exhausted_for_existing):
        raise ApiError("PROMO_CODE_INVALID", 422, "Promo code invalid")
    if not (promo.valid_from <= now <= promo.valid_until):
        raise ApiError("PROMO_CODE_INVALID", 422, "Promo code invalid")


def _calculate_discount(promo: PromoCode, total_amount: Decimal) -> Decimal:
    if total_amount < promo.min_order_amount:
        raise ApiError("PROMO_CODE_MIN_AMOUNT", 422, "Order amount below promo minimum")

    if promo.discount_type == DiscountType.PERCENTAGE:
        discount = total_amount * promo.discount_value / Decimal("100")
        max_discount = total_amount * Decimal("0.7")
        if discount > max_discount:
            discount = max_discount
    else:
        discount = promo.discount_value
        if discount > total_amount:
            discount = total_amount

    return discount


@app.post("/auth/register", response_model=AuthRegisterResponse, status_code=201)
def register_user(payload: AuthRegisterRequest, db: Session = Depends(get_db)) -> AuthRegisterResponse:
    existing = db.query(User).filter(User.email == payload.email).one_or_none()
    if existing:
        raise ApiError("VALIDATION_ERROR", 400, "Email already registered", {"fields": [{"field": "email", "message": "Already exists"}]})

    role_value = _enum_value(payload.role) if payload.role else UserRole.USER.value
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=UserRole(role_value),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return AuthRegisterResponse(
        id=str(user.id),
        email=user.email,
        role=user.role.value,
        created_at=user.created_at,
    )


@app.post("/auth/login", response_model=TokenResponse)
def login_user(payload: AuthLoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.email == payload.email).one_or_none()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise ApiError("TOKEN_INVALID", 401, "Invalid credentials")

    return TokenResponse(
        access_token=create_access_token(str(user.id), user.role.value),
        refresh_token=create_refresh_token(str(user.id), user.role.value),
        token_type="bearer",
    )


@app.post("/auth/refresh", response_model=TokenResponse)
def refresh_token(payload: AuthRefreshRequest, db: Session = Depends(get_db)) -> TokenResponse:
    token_payload = verify_token(payload.refresh_token, "refresh")
    user = db.query(User).filter(User.id == token_payload.get("sub")).one_or_none()
    if not user:
        raise ApiError("REFRESH_TOKEN_INVALID", 401, "User not found")

    return TokenResponse(
        access_token=create_access_token(str(user.id), user.role.value),
        refresh_token=payload.refresh_token,
        token_type="bearer",
    )


@app.get("/products", response_model=ProductListResponse, dependencies=[Depends(get_current_user)])
def list_products(
    page: int = Query(0, ge=0),
    size: int = Query(20, ge=1),
    status: ProductStatus | None = None,
    category: str | None = None,
    db: Session = Depends(get_db),
) -> ProductListResponse:
    query = db.query(Product)
    if status:
        query = query.filter(Product.status == status)
    if category:
        query = query.filter(Product.category == category)

    total = query.count()
    items = query.offset(page * size).limit(size).all()

    return ProductListResponse(
        items=[_to_product_response(product) for product in items],
        totalElements=total,
        page=page,
        size=size,
    )


@app.post("/products", response_model=ProductResponse, status_code=201)
def create_product(
    payload: ProductCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.SELLER.value, UserRole.ADMIN.value)),
) -> ProductResponse:
    seller_id = user.id
    if user.role == UserRole.ADMIN and payload.seller_id:
        target_seller = db.query(User).filter(User.id == payload.seller_id).one_or_none()
        if not target_seller or target_seller.role != UserRole.SELLER:
            raise ApiError(
                "VALIDATION_ERROR",
                400,
                "Invalid seller_id",
                {"fields": [{"field": "seller_id", "message": "Seller not found or has invalid role"}]},
            )
        seller_id = target_seller.id

    if user.role == UserRole.SELLER and payload.seller_id and payload.seller_id != user.id:
        raise ApiError("ACCESS_DENIED", 403, "Access denied")

    product = Product(
        name=payload.name,
        description=payload.description,
        price=payload.price,
        stock=payload.stock,
        category=payload.category,
        status=ProductStatus(_enum_value(payload.status)),
        seller_id=seller_id,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return _to_product_response(product)


@app.get("/products/{id}", response_model=ProductResponse)
def get_product(
    id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> ProductResponse:
    product = db.query(Product).filter(Product.id == id).one_or_none()
    if not product:
        raise ApiError("PRODUCT_NOT_FOUND", 404, "Product not found")
    return _to_product_response(product)


@app.put("/products/{id}", response_model=ProductResponse)
def update_product(
    id: UUID,
    payload: ProductUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.SELLER.value, UserRole.ADMIN.value)),
) -> ProductResponse:
    product = db.query(Product).filter(Product.id == id).one_or_none()
    if not product:
        raise ApiError("PRODUCT_NOT_FOUND", 404, "Product not found")

    _require_product_owner(product, user)

    data = payload.model_dump(exclude_unset=True)
    if "status" in data and data["status"] is not None:
        data["status"] = ProductStatus(_enum_value(data["status"]))
    for key, value in data.items():
        setattr(product, key, value)

    db.commit()
    db.refresh(product)
    return _to_product_response(product)


@app.delete("/products/{id}", status_code=204, response_model=None)
def delete_product(
    id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.SELLER.value, UserRole.ADMIN.value)),
) -> None:
    product = db.query(Product).filter(Product.id == id).one_or_none()
    if not product:
        raise ApiError("PRODUCT_NOT_FOUND", 404, "Product not found")

    _require_product_owner(product, user)

    product.status = ProductStatus.ARCHIVED
    db.commit()


@app.post("/orders", response_model=OrderResponse, status_code=201)
def create_order(
    payload: OrderCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.USER.value, UserRole.ADMIN.value)),
) -> OrderResponse:
    requested: dict[str, int] = {}
    for item in payload.items:
        product_id = str(item.product_id)
        requested[product_id] = requested.get(product_id, 0) + item.quantity

    has_active_transaction = db.in_transaction()
    transaction_context = db.begin_nested() if has_active_transaction else db.begin()

    with transaction_context:
        _check_rate_limit(db, str(user.id), OperationType.CREATE_ORDER)

        active_order = (
            db.query(Order)
            .filter(Order.user_id == user.id, Order.status.in_([OrderStatus.CREATED, OrderStatus.PAYMENT_PENDING]))
            .first()
        )
        if active_order:
            raise ApiError("ORDER_HAS_ACTIVE", 409, "User has active order")

        products = (
            db.query(Product)
            .filter(Product.id.in_(list(requested.keys())))
            .with_for_update()
            .all()
        )
        product_map = {str(product.id): product for product in products}

        for product_id in requested:
            product = product_map.get(product_id)
            if not product:
                raise ApiError("PRODUCT_NOT_FOUND", 404, "Product not found")
            if product.status != ProductStatus.ACTIVE:
                raise ApiError("PRODUCT_INACTIVE", 409, "Product inactive")

        insufficient = []
        for product_id, qty in requested.items():
            product = product_map[product_id]
            if product.stock < qty:
                insufficient.append(
                    {
                        "product_id": product_id,
                        "requested": qty,
                        "available": product.stock,
                    }
                )
        if insufficient:
            raise ApiError(
                "INSUFFICIENT_STOCK",
                409,
                "Insufficient stock",
                {"items": insufficient},
            )

        for product_id, qty in requested.items():
            product_map[product_id].stock -= qty

        total_amount = Decimal("0")
        order_items = []
        for item in payload.items:
            product = product_map[str(item.product_id)]
            price = product.price
            total_amount += price * item.quantity
            order_items.append(
                OrderItem(
                    product_id=product.id,
                    quantity=item.quantity,
                    price_at_order=price,
                )
            )

        order = Order(
            user_id=user.id,
            status=OrderStatus.CREATED,
            total_amount=total_amount,
            discount_amount=Decimal("0"),
        )

        if payload.promo_code:
            promo = db.query(PromoCode).filter(PromoCode.code == payload.promo_code).one_or_none()
            if not promo:
                raise ApiError("PROMO_CODE_INVALID", 422, "Promo code invalid")
            _validate_promo_basic(promo)
            discount = _calculate_discount(promo, total_amount)
            promo.current_uses += 1
            order.promo_code_id = promo.id
            order.discount_amount = discount
            order.total_amount = total_amount - discount

        order.items = order_items
        db.add(order)
        db.add(UserOperation(user_id=user.id, operation_type=OperationType.CREATE_ORDER))

    if has_active_transaction and db.in_transaction():
        db.commit()

    db.refresh(order)
    return _to_order_response(order)


@app.get("/orders/{id}", response_model=OrderResponse)
def get_order(
    id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.USER.value, UserRole.ADMIN.value)),
) -> OrderResponse:
    order = db.query(Order).filter(Order.id == id).one_or_none()
    if not order:
        raise ApiError("ORDER_NOT_FOUND", 404, "Order not found")

    _require_order_owner(order, user)
    return _to_order_response(order)


@app.put("/orders/{id}", response_model=OrderResponse)
def update_order(
    id: UUID,
    payload: OrderUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.USER.value, UserRole.ADMIN.value)),
) -> OrderResponse:
    order = db.query(Order).filter(Order.id == id).one_or_none()
    if not order:
        raise ApiError("ORDER_NOT_FOUND", 404, "Order not found")

    _require_order_owner(order, user)

    if order.status != OrderStatus.CREATED:
        raise ApiError("INVALID_STATE_TRANSITION", 409, "Invalid state transition")

    requested: dict[str, int] = {}
    for item in payload.items:
        product_id = str(item.product_id)
        requested[product_id] = requested.get(product_id, 0) + item.quantity

    has_active_transaction = db.in_transaction()
    transaction_context = db.begin_nested() if has_active_transaction else db.begin()

    with transaction_context:
        _check_rate_limit(db, str(user.id), OperationType.UPDATE_ORDER)

        product_ids = set(requested.keys()) | {str(item.product_id) for item in order.items}
        products = (
            db.query(Product)
            .filter(Product.id.in_(list(product_ids)))
            .with_for_update()
            .all()
        )
        product_map = {str(product.id): product for product in products}

        for item in order.items:
            product = product_map.get(str(item.product_id))
            if product:
                product.stock += item.quantity

        for product_id in requested:
            product = product_map.get(product_id)
            if not product:
                raise ApiError("PRODUCT_NOT_FOUND", 404, "Product not found")
            if product.status != ProductStatus.ACTIVE:
                raise ApiError("PRODUCT_INACTIVE", 409, "Product inactive")

        insufficient = []
        for product_id, qty in requested.items():
            product = product_map[product_id]
            if product.stock < qty:
                insufficient.append(
                    {
                        "product_id": product_id,
                        "requested": qty,
                        "available": product.stock,
                    }
                )
        if insufficient:
            raise ApiError(
                "INSUFFICIENT_STOCK",
                409,
                "Insufficient stock",
                {"items": insufficient},
            )

        for product_id, qty in requested.items():
            product_map[product_id].stock -= qty

        total_amount = Decimal("0")
        new_items = []
        for item in payload.items:
            product = product_map[str(item.product_id)]
            price = product.price
            total_amount += price * item.quantity
            new_items.append(
                OrderItem(
                    product_id=product.id,
                    quantity=item.quantity,
                    price_at_order=price,
                )
            )

        order.items = new_items
        order.discount_amount = Decimal("0")
        order.total_amount = total_amount

        if order.promo_code_id:
            promo = db.query(PromoCode).filter(PromoCode.id == order.promo_code_id).one_or_none()
            if not promo:
                raise ApiError("PROMO_CODE_INVALID", 422, "Promo code invalid")

            _validate_promo_basic(promo, allow_exhausted_for_existing=True)

            if total_amount < promo.min_order_amount:
                if promo.current_uses > 0:
                    promo.current_uses -= 1
                order.promo_code_id = None
            else:
                discount = _calculate_discount(promo, total_amount)
                order.discount_amount = discount
                order.total_amount = total_amount - discount

        db.add(order)
        db.add(UserOperation(user_id=user.id, operation_type=OperationType.UPDATE_ORDER))

    if has_active_transaction and db.in_transaction():
        db.commit()

    db.refresh(order)
    return _to_order_response(order)


@app.post("/orders/{id}/cancel", response_model=OrderResponse)
def cancel_order(
    id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.USER.value, UserRole.ADMIN.value)),
) -> OrderResponse:
    order = db.query(Order).filter(Order.id == id).one_or_none()
    if not order:
        raise ApiError("ORDER_NOT_FOUND", 404, "Order not found")

    _require_order_owner(order, user)

    if order.status not in {OrderStatus.CREATED, OrderStatus.PAYMENT_PENDING}:
        raise ApiError("INVALID_STATE_TRANSITION", 409, "Invalid state transition")

    has_active_transaction = db.in_transaction()
    transaction_context = db.begin_nested() if has_active_transaction else db.begin()

    with transaction_context:
        product_ids = [str(item.product_id) for item in order.items]
        products = (
            db.query(Product)
            .filter(Product.id.in_(product_ids))
            .with_for_update()
            .all()
        )
        product_map = {str(product.id): product for product in products}

        for item in order.items:
            product = product_map.get(str(item.product_id))
            if product:
                product.stock += item.quantity

        if order.promo_code_id:
            promo = db.query(PromoCode).filter(PromoCode.id == order.promo_code_id).one_or_none()
            if promo and promo.current_uses > 0:
                promo.current_uses -= 1

        order.status = OrderStatus.CANCELED
        db.add(order)

    if has_active_transaction and db.in_transaction():
        db.commit()

    db.refresh(order)
    return _to_order_response(order)


@app.post("/promo-codes", response_model=PromoCodeResponse, status_code=201)
def create_promo_code(
    payload: PromoCodeCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.SELLER.value, UserRole.ADMIN.value)),
) -> PromoCodeResponse:
    promo = PromoCode(
        code=payload.code,
        discount_type=DiscountType(_enum_value(payload.discount_type)),
        discount_value=payload.discount_value,
        min_order_amount=payload.min_order_amount,
        max_uses=payload.max_uses,
        valid_from=payload.valid_from,
        valid_until=payload.valid_until,
        active=payload.active if payload.active is not None else True,
    )
    db.add(promo)
    db.commit()
    db.refresh(promo)

    return PromoCodeResponse(
        id=str(promo.id),
        code=promo.code,
        discount_type=promo.discount_type.value,
        discount_value=promo.discount_value,
        min_order_amount=promo.min_order_amount,
        max_uses=promo.max_uses,
        current_uses=promo.current_uses,
        valid_from=promo.valid_from,
        valid_until=promo.valid_until,
        active=promo.active,
    )
