# Multi-stage, so the project builds and runs with no JDK or Maven installed
# on the host. The build stage caches dependencies in its own layer: editing
# a source file then does not re-download the world.

FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /build

# Dependencies first, keyed only on the POM.
COPY pom.xml .
RUN mvn -B -q dependency:go-offline

COPY src ./src
RUN mvn -B -q clean package -DskipTests

FROM eclipse-temurin:21-jre-alpine AS runtime
WORKDIR /app

# Never run as root.
RUN addgroup -S app && adduser -S -G app app
USER app

COPY --from=build /build/target/*.jar app.jar

EXPOSE 8080

# Container-aware heap sizing, and a container-friendly entropy source so
# session id generation does not block on a cold /dev/random.
ENV JAVA_TOOL_OPTIONS="-XX:MaxRAMPercentage=75 -Djava.security.egd=file:/dev/./urandom"

HEALTHCHECK --interval=15s --timeout=3s --start-period=40s --retries=5 \
    CMD wget -qO- http://127.0.0.1:8080/actuator/health | grep -q '"status":"UP"'

ENTRYPOINT ["java", "-jar", "/app/app.jar"]
