import org.jetbrains.compose.desktop.application.dsl.TargetFormat
import org.gradle.api.artifacts.component.ModuleComponentIdentifier

plugins {
    kotlin("jvm") version "2.4.20"
    kotlin("plugin.serialization") version "2.4.20"
    id("org.jetbrains.compose") version "1.12.2"
    id("org.jetbrains.kotlin.plugin.compose") version "2.4.20"
}

group = "com.spiritscout"
val versionSource = project.file("../src/spiritscout/__init__.py")
val appVersion = Regex("""__version__\s*=\s*"([^"]+)"""")
    .find(versionSource.readText())
    ?.groupValues
    ?.get(1)
    ?: error("无法从 ${versionSource.path} 读取版本")
version = appVersion

kotlin {
    jvmToolchain(21)
}

dependencies {
    implementation(compose.desktop.currentOs)
    implementation(compose.materialIconsExtended)
    implementation("io.github.moriafly:salt-ui:3.0.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-swing:1.10.2")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.10.0")
    implementation("net.java.dev.jna:jna-platform:5.18.1")
    testImplementation(kotlin("test"))
}

tasks.named<ProcessResources>("processResources") {
    from("../src/spiritscout/web/static/js/i18n.en.js") {
        into("i18n")
        rename { "en.js" }
    }
}

val desktopInputDir = layout.buildDirectory.dir("desktop-input")
tasks.register("stageDesktop") {
    dependsOn(tasks.named("jar"))
    notCompatibleWithConfigurationCache("Copies the resolved runtime classpath for jpackage")
    doLast {
        val outputDir = desktopInputDir.get().asFile
        outputDir.deleteRecursively()
        outputDir.mkdirs()

        copy {
            from(tasks.named("jar"))
            into(outputDir)
        }
        configurations.runtimeClasspath.get().incoming.artifacts.forEach { artifact ->
            val coordinate = artifact.id.componentIdentifier
            val prefix = if (coordinate is ModuleComponentIdentifier) {
                "${coordinate.group}-${coordinate.module}-${coordinate.version}"
            } else {
                "dependency"
            }.replace(Regex("[^A-Za-z0-9._-]"), "_")
            copy {
                from(artifact.file)
                into(outputDir)
                rename { "${prefix}-${artifact.file.name}" }
            }
        }
    }
}

compose.desktop {
    application {
        mainClass = "com.spiritscout.desktop.MainKt"
        jvmArgs += listOf(
            "-Dfile.encoding=UTF-8",
            "-Dsun.java2d.uiScale.enabled=true"
        )

        nativeDistributions {
            targetFormats(TargetFormat.Msi)
            packageName = "SpiritScout"
            packageVersion = appVersion
            description = "灵枢 SpiritScout 原生桌面端"
            vendor = "SpiritScout"
            modules(
                "java.net.http",
                "java.naming",
                "java.management",
                "jdk.unsupported"
            )
            windows {
                iconFile.set(project.file("../packaging/windows/icon.ico"))
                menu = true
                shortcut = true
                dirChooser = true
                perUserInstall = true
                upgradeUuid = "56f1ed64-26f1-4af8-a1e8-02cdce43053a"
            }
        }
    }
}
