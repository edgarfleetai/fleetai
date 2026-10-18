# Keycloak — отдельный тестовый OAuth-сервер FleetAI

# Only staging: no production secrets, no production database.
FROM quay.io/keycloak/keycloak:26.2.5
ENV KC_HEALTH_ENABLED=true
ENV KC_METRICS_ENABLED=false
ENV KC_HTTP_ENABLED=true
ENV KC_HTTP_HOST=0.0.0.0
ENV KC_CACHE=local
ENV KC_PROXY_HEADERS=xforwarded
ENV KC_HOSTNAME_STRICT=true
EXPOSE 8080
ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
CMD ["start", "--http-port=8080"]
