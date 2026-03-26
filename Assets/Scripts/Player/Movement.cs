using UnityEngine;

/// <summary>
/// 移动组件 - 处理 CS:GO 风格的移动机制
/// 包括：反身移动、移动惩罚、急停检测
/// </summary>
public class Movement : MonoBehaviour
{
    [Header("移动惩罚设置")]
    [Tooltip("移动时射击精度惩罚 (0-1)")]
    public float movementAccuracyPenalty = 0.7f;
    
    [Tooltip("冲刺时射击精度惩罚")]
    public float sprintAccuracyPenalty = 0.3f;
    
    [Tooltip("蹲下时射击精度加成")]
    public float crouchAccuracyBonus = 1.2f;

    [Header("急停设置")]
    [Tooltip("急停阈值 (速度低于此值视为急停)")]
    public float stopThreshold = 0.5f;
    
    [Tooltip("急停冷却时间")]
    public float stopCooldown = 0.2f;

    [Header("反身移动设置")]
    [Tooltip("反身移动旋转速度")]
    public float counterStrafeRotationSpeed = 20f;
    
    [Tooltip("反身移动自动旋转启用")]
    public bool autoCounterStrafe = true;

    // 状态
    private Vector3 lastVelocity;
    private Vector3 currentVelocity;
    private bool isStopStrafing;
    private float stopTimer;
    private Vector3 moveDirection;
    private Vector3 previousMoveDirection;

    void Update()
    {
        HandleCounterStrafe();
        UpdateStopStrafing();
    }

    /// <summary>
    /// 处理反身移动
    /// </summary>
    private void HandleCounterStrafe()
    {
        if (!autoCounterStrafe) return;

        // 检测移动方向变化
        if (moveDirection != previousMoveDirection && moveDirection.magnitude > 0.1f)
        {
            // 移动方向改变，触发反身移动
            CounterStrafe();
        }

        previousMoveDirection = moveDirection;
    }

    /// <summary>
    /// 执行反身移动
    /// </summary>
    public void CounterStrafe()
    {
        // 向相反方向快速移动以抵消动量
        // 这会在 PlayerController 中通过输入处理
        // 这里主要提供状态和辅助功能
        
        isStopStrafing = true;
        Invoke(nameof(ResetCounterStrafe), 0.1f);
    }

    /// <summary>
    /// 重置反身移动状态
    /// </summary>
    private void ResetCounterStrafe()
    {
        isStopStrafing = false;
    }

    /// <summary>
    /// 更新急停状态
    /// </summary>
    private void UpdateStopStrafing()
    {
        if (stopTimer > 0)
        {
            stopTimer -= Time.deltaTime;
        }
    }

    /// <summary>
    /// 设置移动方向
    /// </summary>
    public void SetMoveDirection(Vector3 direction)
    {
        moveDirection = direction;
    }

    /// <summary>
    /// 设置速度
    /// </summary>
    public void SetVelocity(Vector3 velocity)
    {
        lastVelocity = currentVelocity;
        currentVelocity = velocity;
    }

    /// <summary>
    /// 获取移动精度修正值
    /// </summary>
    /// <param name="isMoving">是否正在移动</param>
    /// <param name="isSprinting">是否正在冲刺</param>
    /// <param name="isCrouching">是否正在蹲下</param>
    /// <param name="isStopped">是否急停</param>
    /// <returns>精度修正系数</returns>
    public float GetAccuracyModifier(bool isMoving, bool isSprinting, bool isCrouching, bool isStopped)
    {
        float modifier = 1f;

        // 急停时精度最佳
        if (isStopped)
        {
            modifier = 1f;
        }
        // 冲刺时精度最差
        else if (isSprinting)
        {
            modifier = sprintAccuracyPenalty;
        }
        // 正常移动
        else if (isMoving)
        {
            modifier = movementAccuracyPenalty;
        }

        // 蹲下加成
        if (isCrouching)
        {
            modifier *= crouchAccuracyBonus;
        }

        return modifier;
    }

    /// <summary>
    /// 检查是否急停
    /// </summary>
    public bool IsStopStrafing()
    {
        return isStopStrafing;
    }

    /// <summary>
    /// 检查是否可以急停射击
    /// </summary>
    /// <param name="currentSpeed">当前速度</param>
    /// <returns>是否可以急停射击</returns>
    public bool CanStopStrafeShoot(float currentSpeed)
    {
        return currentSpeed < stopThreshold;
    }

    /// <summary>
    /// 获取当前速度
    /// </summary>
    public Vector3 GetCurrentVelocity()
    {
        return currentVelocity;
    }

    /// <summary>
    /// 获取上一帧速度
    /// </summary>
    public Vector3 GetLastVelocity()
    {
        return lastVelocity;
    }

    /// <summary>
    /// 检测速度变化
    /// </summary>
    public bool IsVelocityChanging()
    {
        return (currentVelocity - lastVelocity).magnitude > 0.1f;
    }
}
