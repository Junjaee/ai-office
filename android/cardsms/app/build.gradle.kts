import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// 서명: CI 가 GitHub Secrets 를 환경변수로 준다. 없으면(로컬) debug 키로 서명해 설치는 되게 한다.
val keystoreFile: String? = System.getenv("CARDSMS_KEYSTORE_FILE")

android {
    namespace = "dev.aioffice.cardsms"
    compileSdk = 34

    defaultConfig {
        applicationId = "dev.aioffice.cardsms"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }

    signingConfigs {
        create("release") {
            if (keystoreFile != null) {
                storeFile = file(keystoreFile)
                storePassword = System.getenv("CARDSMS_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("CARDSMS_KEY_ALIAS")
                keyPassword = System.getenv("CARDSMS_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = if (keystoreFile != null) signingConfigs.getByName("release")
                            else signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin { compilerOptions { jvmTarget.set(JvmTarget.JVM_17) } }

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.work:work-runtime-ktx:2.9.1")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")   // JVM 테스트에서 org.json 실제 구현
}
