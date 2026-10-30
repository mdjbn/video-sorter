import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
}

// 正式签名配置：让每次构建（本机与 CI）都用同一张证书，用户才能「覆盖升级」而不必卸载重装。
// 证书与密码放在 android/keystore.properties（不进 git）里；CI 由 workflow 从 secrets 还原出同名文件。
// 文件不存在时退回 Android 默认 debug 签名（本地临时构建仍可用，但产物不可用于发布）。
val keystorePropsFile = rootProject.file("keystore.properties")
val keystoreProps = Properties().apply {
    if (keystorePropsFile.exists()) keystorePropsFile.inputStream().use { load(it) }
}
val hasReleaseSigning = keystoreProps.getProperty("storeFile") != null &&
    rootProject.file(keystoreProps.getProperty("storeFile")).exists()

// versionName 是唯一真源，versionCode 由它推导：1.3.7 -> 10307（Android 要求 versionCode 单调递增）
val appVersionName = "1.3.7"
val appVersionCode = appVersionName.split(".").let {
    it[0].toInt() * 10000 + it[1].toInt() * 100 + it[2].toInt()
}

android {
    namespace = "com.videosorter.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.videosorter.app"
        minSdk = 24
        targetSdk = 35
        versionCode = appVersionCode
        versionName = appVersionName
    }

    signingConfigs {
        if (hasReleaseSigning) {
            create("release") {
                storeFile = rootProject.file(keystoreProps.getProperty("storeFile"))
                storePassword = keystoreProps.getProperty("storePassword")
                keyAlias = keystoreProps.getProperty("keyAlias")
                keyPassword = keystoreProps.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            // 发版用的是 release 变体；有正式证书就签它（没有则出 unsigned 包，CI 的 apksigner 校验会拦下）
            if (hasReleaseSigning) signingConfig = signingConfigs.getByName("release")
        }
        debug {
            // 调试包也签同一张证书：本机 adb install -r 与用户升级行为一致，方便验证覆盖安装；
            // 没有证书时保持 Android 默认 debug 签名，本地开发不受影响。
            if (hasReleaseSigning) signingConfig = signingConfigs.getByName("release")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    // 按 ABI 拆分安装包：arm64-v8a 与 armeabi-v7a 各出一个 APK
    splits {
        abi {
            isEnable = true
            reset()
            include("arm64-v8a", "armeabi-v7a")
            isUniversalApk = false
        }
    }

    buildFeatures {
        buildConfig = true
        compose = true
    }
    packaging { resources.excludes += "/META-INF/{AL2.0,LGPL2.1}" }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.12.01")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    testImplementation("junit:junit:4.13.2")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.core:core-ktx:1.15.0")

    implementation("androidx.media3:media3-exoplayer:1.5.1")
    implementation("androidx.media3:media3-datasource:1.5.1")
    implementation("androidx.media3:media3-database:1.5.1")
    implementation("androidx.media3:media3-exoplayer-hls:1.5.1")
    implementation("androidx.media3:media3-ui:1.5.1")

    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    implementation("io.coil-kt:coil-compose:2.7.0")
}
