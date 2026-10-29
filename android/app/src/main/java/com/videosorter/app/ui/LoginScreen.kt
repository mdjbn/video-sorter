package com.videosorter.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.Visibility
import androidx.compose.material.icons.rounded.VisibilityOff
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.videosorter.app.data.Api
import com.videosorter.app.data.LanDiscovery
import com.videosorter.app.data.Session
import kotlinx.coroutines.launch

@Composable
fun LoginScreen(
    session: Session,
    themeMode: String,
    onThemeChange: (String) -> Unit,
    onLoggedIn: (Api, String) -> Unit,
) {
    val t = tokens()
    val scope = rememberCoroutineScope()
    var server by remember { mutableStateOf(session.current.ifBlank { "192.168.1.8:8080" }) }
    var user by remember { mutableStateOf(session.lastUser().ifBlank { "admin" }) }
    var pass by remember { mutableStateOf(session.password(Session.normalize(server))) }
    var savePass by remember { mutableStateOf(session.savePassword) }
    var keepLogin by remember { mutableStateOf(session.keepLogin) }
    var showPass by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var err by remember { mutableStateOf("") }
    var scanning by remember { mutableStateOf(false) }
    var scanNote by remember { mutableStateOf("") }
    val saved = remember { session.servers() }

    fun doLogin() {
        if (busy) return
        val base = Session.normalize(server)
        if (base.isEmpty()) {
            err = "请填写服务器地址"; return
        }
        if (user.isBlank() || pass.isBlank()) {
            err = "请填写用户名和密码"; return
        }
        busy = true
        err = ""
        scope.launch {
            try {
                val api = Api(base)
                if (!api.ping()) {
                    err = "连不上服务器，请检查地址和端口"
                } else {
                    val auth = api.login(user, pass)
                    session.savePassword = savePass
                    session.keepLogin = keepLogin
                    session.setPassword(if (savePass) pass else "", base)
                    onLoggedIn(api, auth.user?.username ?: user)
                }
            } catch (e: Exception) {
                err = e.message ?: "登录失败"
            } finally {
                busy = false
            }
        }
    }

    Box(
        Modifier
            .fillMaxSize()
            .background(t.bg)
    ) {
        // 顶部绿色氛围光
        Box(
            Modifier
                .fillMaxWidth()
                .height(420.dp)
                .background(
                    Brush.radialGradient(
                        colors = listOf(t.accent.copy(alpha = 0.13f), Color.Transparent),
                        radius = 900f,
                    )
                )
        )
        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 26.dp)
                .padding(top = 64.dp, bottom = 32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            // 品牌
            Box(
                Modifier
                    .size(52.dp)
                    .clip(RoundedCornerShape(16.dp))
                    .background(Brush.linearGradient(listOf(Color(0xFF5FECAB), Color(0xFF2FBF7C)))),
                contentAlignment = Alignment.Center,
            ) {
                Text("▶", color = Color(0xFF04160D), fontSize = 20.sp)
            }
            Spacer(Modifier.height(18.dp))
            Text("视频整理", color = t.text, fontSize = 21.sp, fontWeight = FontWeight.Bold)
            Text(
                "VIDEO SORTER · 连接你的服务器",
                color = t.muted2,
                fontSize = 11.sp,
                letterSpacing = 0.8.sp,
                modifier = Modifier.padding(top = 7.dp),
            )
            Spacer(Modifier.height(26.dp))

            // 服务器地址
            FieldLabel("服务器地址")
            GlassField(
                value = server,
                onValueChange = { server = it; err = "" },
                placeholder = "192.168.1.8:8080",
                keyboardType = androidx.compose.ui.text.input.KeyboardType.Uri,
            )

            Row(
                Modifier.fillMaxWidth().padding(top = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    if (scanning) "扫描中…" else "扫描局域网",
                    color = t.accent,
                    fontSize = 11.5.sp,
                    modifier = Modifier
                        .clip(RoundedCornerShape(8.dp))
                        .clickable(enabled = !scanning) {
                            scanning = true
                            scanNote = "正在寻找同一 Wi-Fi 下的服务器…"
                            scope.launch {
                                val found = runCatching { LanDiscovery.scan() }.getOrDefault(emptyList())
                                if (found.isEmpty()) {
                                    scanNote = "没找到：确认手机与服务器在同一 Wi-Fi"
                                } else {
                                    server = found.first().address
                                    scanNote = "找到 ${found.size} 台，已填入 ${found.first().address}"
                                }
                                scanning = false
                            }
                        }
                        .padding(vertical = 4.dp, horizontal = 2.dp),
                )
                Spacer(Modifier.width(12.dp))
                Text(
                    scanNote,
                    color = t.muted2,
                    fontSize = 10.sp,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            if (saved.isNotEmpty()) {
                Row(
                    Modifier.fillMaxWidth().padding(top = 6.dp),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    saved.take(3).forEach { s ->
                        Text(
                            s.removePrefix("http://").removePrefix("https://"),
                            color = t.muted,
                            fontSize = 10.5.sp,
                            maxLines = 1,
                            modifier = Modifier
                                .clip(RoundedCornerShape(8.dp))
                                .background(t.ink(0.05f))
                                .border(1.dp, t.line, RoundedCornerShape(8.dp))
                                .clickable { server = s }
                                .padding(horizontal = 8.dp, vertical = 5.dp),
                        )
                    }
                }
            }

            Spacer(Modifier.height(16.dp))
            FieldLabel("用户名")
            GlassField(value = user, onValueChange = { user = it; err = "" }, placeholder = "admin")

            Spacer(Modifier.height(16.dp))
            FieldLabel("密码")
            GlassField(
                value = pass,
                onValueChange = { pass = it; err = "" },
                placeholder = "••••••••",
                password = !showPass,
                trailing = {
                    Icon(
                        if (showPass) Icons.Rounded.VisibilityOff else Icons.Rounded.Visibility,
                        contentDescription = null,
                        tint = t.muted,
                        modifier = Modifier
                            .size(17.dp)
                            .clickable { showPass = !showPass },
                    )
                },
                onDone = { doLogin() },
            )

            Spacer(Modifier.height(12.dp))
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                CheckLine("保存密码", savePass) { savePass = it; session.savePassword = it }
                CheckLine("七天内保持登录", keepLogin) { keepLogin = it; session.keepLogin = it }
            }

            if (err.isNotEmpty()) {
                Text(
                    err,
                    color = t.danger,
                    fontSize = 11.5.sp,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 14.dp)
                        .clip(RoundedCornerShape(10.dp))
                        .background(t.danger.copy(alpha = 0.1f))
                        .border(1.dp, t.danger.copy(alpha = 0.28f), RoundedCornerShape(10.dp))
                        .padding(horizontal = 11.dp, vertical = 9.dp),
                )
            }

            Spacer(Modifier.height(20.dp))
            GradientButton(
                text = if (busy) "登录中…" else "登录",
                onClick = { doLogin() },
                enabled = !busy,
            ) {
                if (busy) {
                    Spacer(Modifier.width(8.dp))
                    CircularProgressIndicator(
                        color = Color(0xFF04160D),
                        strokeWidth = 2.dp,
                        modifier = Modifier.size(14.dp),
                    )
                }
            }

            Spacer(Modifier.height(22.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("light" to "浅色", "dark" to "深色", "auto" to "跟随系统").forEach { (mode, label) ->
                    val on = themeMode == mode
                    Text(
                        label,
                        color = if (on) t.accent else t.muted,
                        fontSize = 11.sp,
                        modifier = Modifier
                            .clip(RoundedCornerShape(9.dp))
                            .background(if (on) t.accent.copy(alpha = 0.14f) else t.ink(0.05f))
                            .border(1.dp, if (on) t.accent.copy(alpha = 0.4f) else t.line, RoundedCornerShape(9.dp))
                            .clickable { onThemeChange(mode) }
                            .padding(horizontal = 11.dp, vertical = 7.dp),
                    )
                }
            }

            Spacer(Modifier.height(18.dp))
            Text(
                "默认账号 admin / admin1234\n数据都保存在服务器端，手机只是遥控器",
                color = t.muted2,
                fontSize = 10.5.sp,
                lineHeight = 16.sp,
                textAlign = androidx.compose.ui.text.style.TextAlign.Center,
            )
            Spacer(Modifier.height(10.dp))
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Box(Modifier.size(5.dp).clip(CircleShape).background(t.accent))
                Text("局域网直连 · 不上传任何第三方", color = t.muted2, fontSize = 10.sp)
            }
        }
    }
}

@Composable
private fun CheckLine(label: String, on: Boolean, onChange: (Boolean) -> Unit) {
    val t = tokens()
    Row(
        Modifier
            .clip(RoundedCornerShape(9.dp))
            .clickable { onChange(!on) }
            .padding(end = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier
                .size(15.dp)
                .clip(RoundedCornerShape(5.dp))
                .background(if (on) t.accent.copy(alpha = 0.9f) else t.ink(0.05f))
                .border(1.dp, if (on) t.accent else t.line2, RoundedCornerShape(5.dp)),
            contentAlignment = Alignment.Center,
        ) {
            if (on) {
                Icon(
                    Icons.Rounded.Check,
                    contentDescription = null,
                    tint = Color(0xFF04160D),
                    modifier = Modifier.size(11.dp),
                )
            }
        }
        Spacer(Modifier.width(7.dp))
        Text(label, color = if (on) t.text else t.muted, fontSize = 11.5.sp)
    }
}

@Composable
private fun FieldLabel(text: String) {
    val t = tokens()
    Text(
        text,
        color = t.muted2,
        fontSize = 11.sp,
        modifier = Modifier
            .fillMaxWidth()
            .padding(bottom = 7.dp, start = 2.dp),
    )
}

@Composable
private fun GlassField(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    password: Boolean = false,
    onDone: () -> Unit = {},
    trailing: (@Composable () -> Unit)? = null,
) {
    val t = tokens()
    val shape = RoundedCornerShape(11.dp)
    Row(
        Modifier
            .fillMaxWidth()
            .height(44.dp)
            .clip(shape)
            .background(t.ink(0.06f))
            .border(1.dp, t.line2, shape)
            .padding(horizontal = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Box(Modifier.weight(1f)) {
            if (value.isEmpty()) {
                Text(placeholder, color = t.muted2, fontSize = 13.sp)
            }
            BasicTextField(
                value = value,
                onValueChange = onValueChange,
                singleLine = true,
                textStyle = TextStyle(color = t.text, fontSize = 13.sp),
                cursorBrush = SolidColor(t.accent),
                visualTransformation = if (password) PasswordVisualTransformation() else VisualTransformation.None,
                keyboardOptions = KeyboardOptions(
                    keyboardType = if (password) KeyboardType.Password else KeyboardType.Text
                ),
                modifier = Modifier.fillMaxWidth(),
            )
        }
        trailing?.invoke()
    }
}
