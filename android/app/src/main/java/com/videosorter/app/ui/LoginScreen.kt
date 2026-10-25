package com.videosorter.app.ui

import androidx.compose.foundation.background
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
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.videosorter.app.data.Api
import com.videosorter.app.data.FoundServer
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
    var server by remember { mutableStateOf(session.current.ifBlank { "192.168.1.8:8080" }) }
    var user by remember { mutableStateOf(session.lastUser()) }
    var pass by remember { mutableStateOf("") }
    var showPass by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var err by remember { mutableStateOf("") }
    var scanning by remember { mutableStateOf(false) }
    var found by remember { mutableStateOf<List<FoundServer>>(emptyList()) }
    var scanNote by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()
    val saved = remember { session.servers() }

    fun doLogin() {
        if (busy) return
        val base = Session.normalize(server)
        if (base.isEmpty()) { err = "请填写服务器地址"; return }
        if (user.isBlank() || pass.isBlank()) { err = "请填写用户名和密码"; return }
        busy = true; err = ""
        scope.launch {
            try {
                val api = Api(base)
                if (!api.ping()) {
                    err = "连不上服务器，请检查地址和端口"
                } else {
                    val auth = api.login(user, pass)
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
        modifier = Modifier
            .fillMaxSize()
            .background(
                Brush.verticalGradient(
                    listOf(
                        MaterialTheme.colorScheme.background,
                        MaterialTheme.colorScheme.surfaceVariant,
                        MaterialTheme.colorScheme.background,
                    )
                )
            ),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 24.dp, vertical = 48.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Box(
                modifier = Modifier
                    .size(56.dp)
                    .background(Accent, RoundedCornerShape(16.dp)),
                contentAlignment = Alignment.Center,
            ) {
                Box(
                    modifier = Modifier
                        .size(0.dp)
                        .background(Accent),
                )
                Text("▶", fontSize = 22.sp, color = MaterialTheme.colorScheme.onPrimary)
            }
            Spacer(Modifier.height(14.dp))
            Text("视频整理", fontSize = 26.sp, fontWeight = FontWeight.Bold)
            Text(
                "VIDEO SORTER · 连接你的服务器",
                fontSize = 11.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 4.dp),
            )
            Spacer(Modifier.height(28.dp))

            Surface(
                shape = RoundedCornerShape(18.dp),
                color = MaterialTheme.colorScheme.surface,
                tonalElevation = 2.dp,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(Modifier.padding(18.dp)) {
                    Text("服务器地址", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    OutlinedTextField(
                        value = server,
                        onValueChange = { server = it; err = "" },
                        singleLine = true,
                        placeholder = { Text("192.168.1.8:8080") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = 6.dp),
                    )
                    if (saved.isNotEmpty()) {
                        Row(
                            Modifier
                                .fillMaxWidth()
                                .padding(top = 8.dp),
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            saved.take(3).forEach { s ->
                                Surface(
                                    shape = RoundedCornerShape(20.dp),
                                    color = MaterialTheme.colorScheme.surfaceVariant,
                                    modifier = Modifier.clickable { server = s },
                                ) {
                                    Text(
                                        s.removePrefix("http://"),
                                        fontSize = 11.sp,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                                    )
                                }
                            }
                        }
                    }

                    Row(
                        Modifier
                            .fillMaxWidth()
                            .padding(top = 2.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        TextButton(
                            enabled = !scanning,
                            onClick = {
                                scanning = true; scanNote = ""
                                scope.launch {
                                    try {
                                        val list = LanDiscovery.scan()
                                        found = list
                                        if (list.isEmpty()) scanNote = "没找到服务器：确认手机和服务器在同一 Wi-Fi，且服务器已启动"
                                        else if (list.size == 1) server = list[0].address
                                    } catch (e: Exception) {
                                        scanNote = e.message ?: "扫描失败"
                                    } finally {
                                        scanning = false
                                    }
                                }
                            },
                        ) { Text(if (scanning) "扫描中…" else "扫描局域网", fontSize = 12.sp) }
                        if (scanNote.isNotEmpty()) {
                            Text(scanNote, fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                    if (found.isNotEmpty()) {
                        Column(Modifier.padding(top = 4.dp)) {
                            found.forEach { f ->
                                Surface(
                                    shape = RoundedCornerShape(10.dp),
                                    color = MaterialTheme.colorScheme.surfaceVariant,
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(vertical = 3.dp)
                                        .clickable { server = f.address },
                                ) {
                                    Column(Modifier.padding(horizontal = 12.dp, vertical = 8.dp)) {
                                        Text(f.name, fontSize = 12.sp)
                                        Text(
                                            f.address,
                                            fontSize = 11.sp,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        )
                                    }
                                }
                            }
                        }
                    }

                    Spacer(Modifier.height(14.dp))
                    Text("用户名", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    OutlinedTextField(
                        value = user,
                        onValueChange = { user = it; err = "" },
                        singleLine = true,
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = 6.dp),
                    )

                    Spacer(Modifier.height(14.dp))
                    Text("密码", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    OutlinedTextField(
                        value = pass,
                        onValueChange = { pass = it; err = "" },
                        singleLine = true,
                        visualTransformation = if (showPass) VisualTransformation.None else PasswordVisualTransformation(),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                        trailingIcon = {
                            IconButton(onClick = { showPass = !showPass }) {
                                Icon(
                                    if (showPass) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                                    contentDescription = null,
                                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        },
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = 6.dp),
                    )

                    if (err.isNotEmpty()) {
                        Text(err, color = MaterialTheme.colorScheme.error, fontSize = 12.sp, modifier = Modifier.padding(top = 10.dp))
                    }

                    Button(
                        onClick = { doLogin() },
                        enabled = !busy,
                        shape = RoundedCornerShape(12.dp),
                        colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = 18.dp)
                            .height(46.dp),
                    ) {
                        if (busy) {
                            CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp, color = MaterialTheme.colorScheme.onPrimary)
                        } else {
                            Text("登录", fontWeight = FontWeight.SemiBold)
                        }
                    }
                }
            }

            Spacer(Modifier.height(18.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("主题", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.width(10.dp))
                Surface(
                    shape = RoundedCornerShape(20.dp),
                    color = MaterialTheme.colorScheme.surfaceVariant,
                    modifier = Modifier.clickable { onThemeChange(nextThemeMode(themeMode, false)) },
                ) {
                    Text(
                        themeLabel(themeMode),
                        fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.padding(horizontal = 14.dp, vertical = 7.dp),
                    )
                }
            }
            Spacer(Modifier.height(12.dp))
            Text(
                "默认账号 admin / admin1234\n数据保存在服务器端，手机只是遥控器",
                fontSize = 11.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                lineHeight = 17.sp,
            )
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(6.dp).background(Accent, CircleShape))
                Text("局域网直连 · 不上传第三方", fontSize = 10.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}
