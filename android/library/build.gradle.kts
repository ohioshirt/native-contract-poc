plugins {
    kotlin("jvm")
    application
}

group = "nativecontract"
version = "1.0.0"

kotlin { jvmToolchain(17) }

application { mainClass.set("nativecontract.TraceRunnerKt") }

dependencies {
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.8.1")
    testImplementation(kotlin("test"))
}

tasks.test { useJUnitPlatform() }
