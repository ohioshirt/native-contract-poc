pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "NativeContractDemo"
include(":app", ":contract-async")
project(":contract-async").projectDir = file("../../android/async-library")

gradle.beforeProject {
    if (path == ":contract-async") {
        layout.buildDirectory.set(rootProject.layout.projectDirectory.dir("app/build/contract-async"))
    }
}
