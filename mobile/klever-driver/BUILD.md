# Сборки Android и iPhone

Сначала выполнить в `mobile/klever-driver`:

```bash
npm install
npx expo-doctor
npm run typecheck
npx expo start
```

Проверка на реальных телефонах в Expo Go возможна для поддерживаемых модулей; сборки через EAS требуют входа в Expo.

## Android APK (для внутреннего тестирования)

```bash
npx eas-cli login
npx eas-cli build --platform android --profile preview
```

Профиль `preview` создаёт APK. EAS вернёт ссылку после успешной сборки.

## iOS

```bash
npx eas-cli login
npx eas-cli build --platform ios --profile preview
```

Профиль `preview` собирает приложение для **симулятора iOS**, а не установочный файл для обычного iPhone. Для установки на реальный iPhone нужна отдельная сборка с Apple Developer, provisioning и регистрацией устройств либо TestFlight.

## Публикация

Потребуются Expo/EAS project ID, Apple Developer account, App Store Connect, Google Play Console, реальные иконки/скриншоты, настройки приватности и проверенные API. Ничего из этого пока не создано или подтверждено. Bundle IDs `ru.kleverpark.driver` предварительные, перед публикацией требуется проверить право на идентификатор.

**Не публиковать** демо как готовый сервис аренды. Текущие данные и брони демонстрационные.
