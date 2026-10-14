buildscript {
    dependencyLocking {
        lockAllConfigurations()
        lockFile.set(rootProject.layout.projectDirectory.file("gradle.lockfile"))
    }
}

plugins {
    id("com.android.application") version "8.13.2" apply false
    kotlin("android") version "2.3.20" apply false
    kotlin("jvm") version "2.3.20" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.3.20" apply false
}

subprojects {
    dependencyLocking {
        lockAllConfigurations()
        if (project.path == ":contract-async") {
            lockFile.set(rootProject.layout.projectDirectory.file("gradle/contract-async.lockfile"))
        }
    }
}

tasks.register("resolveAndLockAll") {
    doFirst {
        require(gradle.startParameter.isWriteDependencyLocks) {
            "resolveAndLockAll requires --write-locks"
        }
    }
    doLast {
        allprojects.forEach { target ->
            target.configurations.filter { it.isCanBeResolved }.forEach { configuration ->
                // Android's self-project dependency has several secondary artifacts.
                // Resolve the graph for locking; build tasks select their artifact views.
                val failures = configuration.incoming.resolutionResult.allDependencies
                    .filterIsInstance<org.gradle.api.artifacts.result.UnresolvedDependencyResult>()
                if (failures.isNotEmpty()) {
                    throw GradleException("Unresolved ${target.path}:${configuration.name}: " +
                        failures.joinToString { "${it.attempted.displayName}: ${it.failure.message}" })
                }
            }
        }
    }
}
